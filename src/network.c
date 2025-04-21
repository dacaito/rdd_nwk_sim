#include "network.h"
#include "payload.h"
#include "node_manager.h"
#include "os.h" // Add this line to include os.h
#include <string.h>
#include <stdint.h>

#define TX_INTERVAL 10000   /**< Minimum interval (in milliseconds) before sending a new packet */
#define RUN_INTERVAL 100     /**< Minimum interval (in milliseconds) between `network_run()` calls */

static volatile NetworkBuffer rx_buffer = { .length = 0 };
static NetworkBuffer tx_buffer = { .length = 0 };
static uint32_t last_tx_timestamp = 0;
static uint32_t lastCheck = 0;


/**
 * @brief Initialize the network module.
 */
void network_init(void) {
    rx_buffer.length = 0;
    tx_buffer.length = 0;
    last_tx_timestamp = 0;
    lastCheck = millis();
}

/**
 * @brief Interrupt handler for receiving a packet.
 *
 * @param data Pointer to received data.
 * @param length Length of received data.
 */
void network_receive_packet(const uint8_t *data, size_t length) {
    if (rx_buffer.length != 0 || length > sizeof(rx_buffer.buffer)) {
        return; // Ignore if there's already a packet pending or if size is too large
    }

    memcpy((void *)rx_buffer.buffer, data, length);
    rx_buffer.length = length;
}

/**
 * @brief Callback function for iterating through nodes and encoding them correctly.
 *
 * Each node is encoded individually using `payload_serialize()` before adding to the TX buffer.
 *
 * @param node Pointer to the node being encoded.
 * @param context Pointer to the `tx_buffer` struct.
 */
static void encode_nodes_callback(const Node *node, void *context) {
    NetworkBuffer *tx = (NetworkBuffer *)context;

    // Ensure there is enough space for an encoded node
    size_t available_space = PAYLOAD_MAX_LENGTH - tx->length;
    if (available_space < (sizeof(Node) + PAYLOAD_HEADER_SIZE)) {
        return; // Not enough space, skip this node
    }

    uint8_t encoded_node[PAYLOAD_MAX_LENGTH + PAYLOAD_HEADER_SIZE];
    int encoded_size = payload_serialize(PAYLOAD_TYPE_NODE, sizeof(Node), (uint8_t *)node, encoded_node, available_space);

    if (encoded_size > 0 && tx->length + encoded_size <= PAYLOAD_MAX_LENGTH) {
        memcpy(&tx->buffer[tx->length], encoded_node, encoded_size);
        tx->length += encoded_size;
    }
}

/**
 * @brief Encodes all available nodes into the transmission buffer.
 */
static void encode_nodes_into_tx_buffer(void) {
    tx_buffer.length = 0;
    node_manager_iterate(encode_nodes_callback, &tx_buffer);
}

/**
 * @brief Callback function for iterating through nodes to find the latest timestamp.
 *
 * @param node Pointer to the current node being checked.
 * @param context Pointer to the latest timestamp variable.
 */
static void find_latest_timestamp(const Node *node, void *context) {
    uint32_t *latest_ts = (uint32_t *)context;
    if (node->timestamp > *latest_ts) {
        *latest_ts = node->timestamp;
    }
}

/**
 * @brief Finds the latest timestamp from all stored nodes.
 *
 * @return The latest timestamp found.
 */
static uint32_t get_latest_node_timestamp(void) {
    uint32_t latest_timestamp = 0;
    node_manager_iterate(find_latest_timestamp, &latest_timestamp);
    return latest_timestamp;
}

/**
 * @brief Handler for processing received payloads.
 *
 * Calls `node_update()` if the payload type is `PAYLOAD_TYPE_NODE`.
 *
 * @param buffer Pointer to the payload data.
 * @param size Size of the payload data.
 */
static void payload_handler(const uint8_t *buffer, size_t size) {
    if (size == sizeof(Node)) {
        Node *received_node = (Node *)buffer;
        node_update(received_node);
    }
}

/**
 * @brief Process received packets and decide whether to transmit.
 */
void network_run(void) {
    unsigned long now = millis();
    
    // Ensure this function runs only at the specified interval
    if (now - lastCheck < RUN_INTERVAL) {
        return;
    }

    // Local copy of RX buffer to avoid concurrency issues
    NetworkBuffer local_rx_buffer = { .length = 0 };

    // Disable IRQ to safely check and copy RX buffer
    __disable_irq();
    if (rx_buffer.length > 0) {
        memcpy(local_rx_buffer.buffer, (const void *)rx_buffer.buffer, rx_buffer.length);
        local_rx_buffer.length = rx_buffer.length;
        rx_buffer.length = 0; // Mark packet as processed
    }
    __enable_irq();

    // Process received message if there was one
    if (local_rx_buffer.length > 0) {
        PayloadHandler_t handlers[8] = {0}; // Array of handlers for payload types
        handlers[PAYLOAD_TYPE_NODE] = payload_handler;
        payload_deserialize(local_rx_buffer.buffer, local_rx_buffer.length, handlers);
    }

    // Determine if we need to send a message
    uint32_t latest_timestamp = get_latest_node_timestamp();

    if (latest_timestamp > last_tx_timestamp + TX_INTERVAL) {
        // Prepare transmission: Encode multiple nodes directly into tx_buffer
        encode_nodes_into_tx_buffer();

        if (tx_buffer.length > 0) {
            // Transmit the encoded nodes
            transmit_packet(tx_buffer.buffer, tx_buffer.length);
            last_tx_timestamp = latest_timestamp;
        }
    }

    // Update last execution time
    lastCheck = now;
}
