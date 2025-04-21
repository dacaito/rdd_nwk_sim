#ifndef PAYLOAD_H
#define PAYLOAD_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define PAYLOAD_MAX_LENGTH 31  // Max payload length (5-bit field)
#define PAYLOAD_HEADER_SIZE 1  // 1-byte header

// Payload Types
typedef enum {
    PAYLOAD_TYPE_NODE = 0,     // Node data
    PAYLOAD_TYPE_SENSOR = 1,   // Sensor data
    PAYLOAD_TYPE_CONFIG = 2,   // Configuration settings
    PAYLOAD_TYPE_CONTROL = 3,  // Control commands
    PAYLOAD_TYPE_DEBUG = 4,    // Debugging info
    PAYLOAD_TYPE_RESERVED_1 = 5,
    PAYLOAD_TYPE_RESERVED_2 = 6,
    PAYLOAD_TYPE_CUSTOM = 7
} PayloadType_t;

// Function pointer for payload handling (direct buffer access)
typedef void (*PayloadHandler_t)(const uint8_t *buffer, size_t size);

/**
 * @brief Serializes a payload into a buffer.
 * @param buf_size The total size of the buffer to prevent overflow.
 * @return The number of bytes written or -1 on failure.
 */
int payload_serialize(PayloadType_t type, uint8_t length, const uint8_t *data, uint8_t *buffer, size_t buf_size);

/**
 * @brief Deserializes a buffer containing multiple messages.
 * Iterates over the buffer and calls handlers for each message.
 * @return The number of messages successfully processed, or -1 on error.
 */
int payload_deserialize(const uint8_t *buffer, size_t buf_size, PayloadHandler_t handlers[]);

/**
 * @brief Validates a payload.
 * @return 1 if valid, 0 if invalid.
 */
int payload_is_valid(const uint8_t *buffer, size_t buf_size);

#endif // PAYLOAD_H
