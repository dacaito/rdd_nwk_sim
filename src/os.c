#include "os.h"
#include <stdio.h>
#include <time.h>

void __disable_irq(void) {
    // Empty implementation
}

void __enable_irq(void) {
    // Empty implementation
}

unsigned long millis() {
    static struct timespec start = {0, 0}; // Stores initial time
    struct timespec ts;

    clock_gettime(CLOCK_MONOTONIC, &ts);

    // Initialize start time on first call
    if (start.tv_sec == 0 && start.tv_nsec == 0) {
        start = ts;
    }

    // Compute difference correctly, handling nanosecond underflow
    time_t sec_diff = ts.tv_sec - start.tv_sec;
    long nsec_diff = ts.tv_nsec - start.tv_nsec;

    if (nsec_diff < 0) { // Borrow 1 second if necessary
        sec_diff -= 1;
        nsec_diff += 1000000000L; // Add 1 second in nanoseconds
    }

    return ((sec_diff * 1000UL) + (nsec_diff / 1000000UL))/PLAYBACK_FACTOR;
}

void transmit_packet(const uint8_t *buffer, size_t length){
    printf("transmit_packet,%zu,", length);
    for (size_t i = 0; i < length; ++i) {
        printf("%02X", buffer[i]);
    }
    printf("\n");


}