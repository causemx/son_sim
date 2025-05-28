from node_base import Node
import sys
import time

def main(node_id):
    # Create node with node_id based identification
    node = Node(node_id=node_id)
    
    # Register other possible nodes in network
    # Nodes will have IDs from 11 to 13 in group 11
    for other_id in range(11, 14):
        if other_id != node_id:  # Don't register self
            node.register_node(other_id)
    
    # Start node
    node.start()
    
    print("\nNode started:")
    print("Group: 11")
    print(f"Node ID: {node_id}")
    print("Handler: Group 1, ID 1\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node.stop()
        print(f"\nNode {node_id} stopped")

def validate_node_id(node_id):
    """Validate node ID format and range"""
    try:
        # Convert to integer and check range (11-13)
        node_id = int(node_id)
        if node_id < 11 or node_id > 13:
            print("Error: Node ID must be between 11 and 13")
            return False
            
        return True
        
    except ValueError:
        print("Error: Invalid node ID format, must be an integer")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python node.py <node_id>")
        print("Example: python node.py 11")
        print("Note: Node ID must be between 11 and 13")
        sys.exit(1)
    
    node_id = sys.argv[1]
    if validate_node_id(node_id):
        main(int(node_id))
    else:
        sys.exit(1)