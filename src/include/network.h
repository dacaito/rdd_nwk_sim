#ifndef NETWORK_H
#define NETWORK_H

#include <stdint.h>
#include <stddef.h> // Add this line to include size_t

typedef struct {
    uint8_t buffer[256];
    size_t length;
} NetworkBuffer;

/**
 * @brief Initializes the network module.
 */
void network_init(void);

/**
 * @brief Called from an interrupt when a packet is received.
 *
 * @param data Pointer to the received packet.
 * @param length Length of the received packet.
 */
void network_receive_packet(const uint8_t *data, size_t length);

/**
 * @brief Regularly called function to process incoming packets and determine 
 *        if transmission is required.
 */
void network_run(void);

#endif // NETWORK_H
