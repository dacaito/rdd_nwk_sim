#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include "network.h"
#include "node_manager.h"
#include "payload.h"
#include "os.h" 


#define MAX_PARAMS 4
#define MAX_PACKET_SIZE 256

void set_nonblocking_stdin(void);
void process_input(char *input);
void handle_node_update(char *params[], int param_count);
void handle_network_receive_packet(char *params[], int param_count);
void handle_get_state(char *params[], int param_count);
void print_node_callback(const Node *node, void *context);

int main(void) {
    unsigned long last_print_time = 0;
    char input[256];

    //set_nonblocking_stdin();  // Make stdin non-blocking
    network_init();


    while (millis() <= 100) {
        if (millis() - last_print_time >= 10) {
            LOG_OUTPUT("stderr: Elapsed time: %lu ms\n", millis());
            last_print_time = millis();
        }
    }

    printf("Enter function call (function,param1,param2,...): ");
    if (fgets(input, sizeof(input), stdin) != NULL) {
        input[strcspn(input, "\n")] = 0;  // Remove newline character
        process_input(input);
    } else {
        printf("Error reading input\n");
    }
    printf("stdio: Finished...\n");
    
    uint8_t hex_data[] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F};
    transmit_packet(hex_data, sizeof(hex_data));

    return 0;
}


void set_nonblocking_stdin(void) {
    int flags = fcntl(STDIN_FILENO, F_GETFL, 0);
    fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK);
}

void process_input(char *input) {
    char *params[MAX_PARAMS];
    int param_count = 0;
    char *saveptr;  // Thread-safe strtok pointer

    // Extract function name
    char *func_name = strtok_r(input, ",", &saveptr);
    if (!func_name) {
        LOG_OUTPUT("ERROR - Invalid input: missing function name\n");
        return;
    }

    // Extract parameters safely
    while (param_count < MAX_PARAMS && (params[param_count] = strtok_r(NULL, ",", &saveptr)) != NULL) {
        param_count++;
    }

    // Print results (example)
    printf("%s", func_name);
    for (int i = 0; i < param_count; i++) {
        printf(",%s", params[i]);
    }
        
    // Handle node_update function
    if (strcmp(func_name, "node_update") == 0) {
        handle_node_update(params, param_count);        
    }
    else if (strcmp(func_name, "network_receive_packet") == 0) {
        handle_network_receive_packet(params, param_count);
    }
    else if (strcmp(func_name, "get_state") == 0) {
        handle_get_state(params, param_count);
    }
    else {
        LOG_OUTPUT("ERROR - Unknown function: %s\n", func_name);
    }
    printf("\n");   
}


void handle_node_update(char *params[], int param_count) {
    if (param_count != 4) {
        LOG_OUTPUT("ERROR - Invalid number of parameters for node_update\n");
        return;
    }

    // Extract parameters
    char *name = params[0];
    char *ts = params[1];
    char *lat = params[2];
    char *lon = params[3];

    // Validate name length
    if (strlen(name) != 4) {
        LOG_OUTPUT("ERROR - Name must be exactly 4 characters long\n");
        return;
    }

    // Create a new node
    Node new_node = {
        .name = {name[0], name[1], name[2], name[3]},
        .timestamp = (uint32_t)atoi(ts),
        .lat = atof(lat),
        .lon = atof(lon),
    };

    // Update the node
    int result = node_update(&new_node);

    if (result > 0) {
        printf(",%d", result);
    } else {
        LOG_OUTPUT("ERROR - updating node: %s\n", name);
    }
}

void handle_network_receive_packet(char *params[], int param_count) {
    if (param_count != 1) {
        LOG_OUTPUT("ERROR - network_receive_packet() requires one parameter.\n");
        return;
    }

    char *hex_str = params[0];
    size_t hex_len = strlen(hex_str);
    size_t byte_count = hex_len / 2;

    // Ensure HEXDATA has a valid length
    if (hex_len % 2 != 0 || byte_count > MAX_PACKET_SIZE) {
        LOG_OUTPUT("ERROR - Invalid HEXDATA length.\n");
        return;
    }

    // Convert HEXDATA to bytes
    uint8_t packet[MAX_PACKET_SIZE];
    for (size_t i = 0; i < byte_count; i++) {
        if (sscanf(hex_str + (i * 2), "%2hhX", &packet[i]) != 1) {
            LOG_OUTPUT("ERROR - HEXDATA contains invalid characters.\n");
            return;
        }
    }

    // Call the actual network handler
    network_receive_packet(packet, byte_count);
}

void print_node_callback(const Node *node, void *context) {
    (void)context;  // Mark context as intentionally unused
    printf(",%.4s,%u,%f,%f", node->name, node->timestamp, node->lat, node->lon);
}

void handle_get_state(char *params[], int param_count) {
    (void)params;  // Mark params as intentionally unused  
    if (param_count != 0) {
        LOG_OUTPUT("ERROR - get_state() does not take any parameters.\n");
        return;
    }

    printf(",%lu", millis());
    // Iterate over all nodes and print their details
    node_manager_iterate(print_node_callback, NULL);
}
