#ifndef NODE_MANAGER_H
#define NODE_MANAGER_H

#include <stdint.h>

/**
 * @brief Represents a network node.
 *
 * This structure holds basic information about a node, including:
 * - A 4-character identifier (without a null terminator)
 * - A Unix timestamp representing the last update time
 * - Geographic coordinates: latitude and longitude
 *
 * The structure is packed so that its in-memory layout matches its serialized form.
 */
typedef struct __attribute__((packed)) {
    char name[4];          /**< 4-character node identifier */
    uint32_t timestamp;    /**< Unix timestamp (last update) */
    float lat;             /**< Latitude coordinate */
    float lon;             /**< Longitude coordinate */
} Node;

/**
 * @brief Initializes the node manager.
 *
 * This function resets the internal node list, clearing all stored node data.
 */
void node_manager_init(void);

/**
 * @brief Updates or adds a node.
 *
 * If a node with the same identifier already exists, the function updates it only
 * if the new node's timestamp is greater than the stored one. If the node does not
 * exist, it is added to the internal storage.
 *
 * @param new_node Pointer to the new node data.
 * @return int On success, returns:
 *         - The difference in seconds between the new and stored timestamps if an update occurred,
 *         - The new node's timestamp if it was added,
 *         - 0 if the new node's timestamp is not newer.
 *         Negative values are returned in case of an error (e.g. NULL pointer, storage full).
 */
int node_update(const Node *new_node);

/**
 * @brief Retrieves node information by its identifier.
 *
 * Searches the internal node list for a node with the given 4-character name.
 * If found, the node data is copied into the provided output pointer.
 *
 * @param name A 4-character array representing the node's name.
 * @param out_node Pointer to a Node structure where the found data will be stored.
 * @return int Returns 0 on success, or a negative value if the node is not found or if an input pointer is NULL.
 */
int node_retrieve(const char name[4], Node *out_node);

/**
 * @brief Deletes a node by its identifier.
 *
 * Removes the node with the given 4-character name from the internal storage.
 *
 * @param name A 4-character array representing the node's name.
 * @return int Returns 0 on success, or a negative value if the node is not found or if an input pointer is NULL.
 */
int node_delete(const char name[4]);

/**
 * @brief Prunes outdated nodes.
 *
 * Removes nodes that have not been updated within the specified age threshold.
 *
 * @param current_timestamp The current Unix timestamp.
 * @param age_threshold The maximum allowed age in seconds for nodes to be retained.
 * @return int The number of nodes that were pruned.
 */
int node_prune(uint32_t current_timestamp, uint32_t age_threshold);

/**
 * @brief Returns the current number of stored nodes.
 *
 * @return int The number of nodes currently managed.
 */
int node_manager_count(void);

/**
 * @brief Iterates over all stored nodes.
 *
 * This function calls the provided callback function for each node in the internal list.
 *
 * @param callback Function pointer to be called with each node and a user-provided context.
 * @param context Pointer to user data that is passed to the callback.
 */
void node_manager_iterate(void (*callback)(const Node *node, void *context), void *context);

#endif /* NODE_MANAGER_H */
