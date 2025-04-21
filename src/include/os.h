#ifndef OS_H
#define OS_H

#include <stdint.h>  // Add this line to include uint8_t
#include <stddef.h>  // Add this line to include size_t
#include <stdio.h>   // Add this line to include stdio.h

#define PLAYBACK_FACTOR 1 // Adjust this value as needed

#define LOG_OUTPUT(...) fprintf(stderr, __VA_ARGS__)

/**
 * @brief Disables interrupts.
 */
void __disable_irq(void);

/**
 * @brief Enables interrupts.
 */
void __enable_irq(void);

/**
 * @brief Transmits a packet.
 * 
 * @param buffer Pointer to the packet data.
 * @param length Length of the packet data.
 */
void transmit_packet(const uint8_t *buffer, size_t length);

/**
 * @brief Returns the system uptime in milliseconds.
 * 
 * The uptime increases by 1000 every PLAYBACK_FACTOR seconds.
 * 
 * @return System uptime in milliseconds.
 */
unsigned long millis(void);

#endif // OS_H
