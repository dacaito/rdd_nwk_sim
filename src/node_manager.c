#include "node_manager.h"
#include <string.h>   // For memcpy, memcmp, and memset
#include <stdint.h>
#include <stdio.h>    // For debugging output if needed

#define MAX_NODES 50

// Internal storage for nodes
static Node node_array[MAX_NODES];
static int node_count = 0;

void node_manager_init(void) {
    node_count = 0;
    memset(node_array, 0, sizeof(node_array));
}

int node_update(const Node *new_node) {
    if (new_node == NULL) {
        return -1;  // Error: NULL pointer
    }

    // Search for an existing node with the same name.
    for (int i = 0; i < node_count; i++) {
        if (memcmp(node_array[i].name, new_node->name, sizeof(node_array[i].name)) == 0) {
            // Found a matching node.
            if (new_node->timestamp > node_array[i].timestamp) {
                int diff = new_node->timestamp - node_array[i].timestamp;
                // Update with new information.
                node_array[i] = *new_node;
                return diff;
            } else {
                // New node timestamp is not newer.
                return 0;
            }
        }
    }

    // If node is not found, add it if there's room.
    if (node_count < MAX_NODES) {
        node_array[node_count++] = *new_node;
        return new_node->timestamp;
    }

    // No space to add new node.
    return -2;
}

int node_retrieve(const char name[4], Node *out_node) {
    if (name == NULL || out_node == NULL) {
        return -1;  // Error: NULL pointer provided
    }

    for (int i = 0; i < node_count; i++) {
        if (memcmp(node_array[i].name, name, sizeof(node_array[i].name)) == 0) {
            *out_node = node_array[i];
            return 0;
        }
    }
    return -1;  // Node not found
}

int node_delete(const char name[4]) {
    if (name == NULL) {
        return -1; // Error: NULL pointer provided
    }
    
    for (int i = 0; i < node_count; i++) {
        if (memcmp(node_array[i].name, name, sizeof(node_array[i].name)) == 0) {
            // Found the node; shift subsequent nodes left.
            for (int j = i; j < node_count - 1; j++) {
                node_array[j] = node_array[j + 1];
            }
            node_count--;
            return 0;
        }
    }
    return -1;  // Node not found
}

int node_prune(uint32_t current_timestamp, uint32_t age_threshold) {
    int pruned_count = 0;
    // Iterate in reverse order so that shifting elements doesn't skip any.
    for (int i = node_count - 1; i >= 0; i--) {
        if (node_array[i].timestamp < current_timestamp - age_threshold) {
            // Delete the node by shifting remaining nodes.
            for (int j = i; j < node_count - 1; j++) {
                node_array[j] = node_array[j + 1];
            }
            node_count--;
            pruned_count++;
        }
    }
    return pruned_count;
}

int node_manager_count(void) {
    return node_count;
}

void node_manager_iterate(void (*callback)(const Node *node, void *context), void *context) {
    if (callback == NULL) {
        return;
    }
    for (int i = 0; i < node_count; i++) {
        callback(&node_array[i], context);
    }
}
