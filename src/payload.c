#include "payload.h"

/**
 * Serialize a payload into a buffer
 */
int payload_serialize(PayloadType_t type, uint8_t length, const uint8_t *data, uint8_t *buffer, size_t buf_size) {
    if (type > 7 || length > PAYLOAD_MAX_LENGTH) {
        return -1;  // Invalid type or length
    }

    size_t required_size = PAYLOAD_HEADER_SIZE + length;
    if (required_size > buf_size) {
        return -1;  // Not enough space in the buffer
    }

    buffer[0] = (type << 5) | (length & 0x1F);  // Pack type and length

    if (length > 0) {
        memcpy(&buffer[1], data, length);
    }

    return required_size;
}

/**
 * Deserialize a buffer and call the corresponding handler for each message
 */
int payload_deserialize(const uint8_t *buffer, size_t buf_size, PayloadHandler_t handlers[]) {
    if (buf_size < PAYLOAD_HEADER_SIZE) {
        return -1;  // Not enough data
    }

    size_t offset = 0;
    int processed_count = 0;

    while (offset < buf_size) {
        if (buf_size - offset < PAYLOAD_HEADER_SIZE) {
            return -1;  // Incomplete message header
        }

        uint8_t header = buffer[offset];
        PayloadType_t type = (PayloadType_t)((header >> 5) & 0x07);
        uint8_t length = header & 0x1F;

        if (length > PAYLOAD_MAX_LENGTH || (offset + PAYLOAD_HEADER_SIZE + length) > buf_size) {
            return -1;  // Invalid payload length
        }

        // Call the handler directly with the buffer slice
        if (handlers[type]) {
            handlers[type](&buffer[offset + 1], length);
        }

        offset += PAYLOAD_HEADER_SIZE + length;
        processed_count++;
    }

    return processed_count;
}

/**
 * Validate a payload
 */
int payload_is_valid(const uint8_t *buffer, size_t buf_size) {
    if (buf_size < PAYLOAD_HEADER_SIZE) {
        return 0;
    }

    uint8_t length = buffer[0] & 0x1F;
    return (length <= PAYLOAD_MAX_LENGTH && buf_size >= PAYLOAD_HEADER_SIZE + length);
}
