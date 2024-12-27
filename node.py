from node_base import Node
import sys
import time


def main(port):
    # Create node
    node = Node(port=port)
    
    # Register other possible nodes
    for p in range(5001, 5010):
        if p != port:  # Don't register self
            node.register_node(port=p)
    
    node.start()
    
    print(f"Node started on port {port} (ID: {port % 1000})")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node.stop()
        print(f"\nNode on port {port} stopped")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python node.py <port>")
        print("Available ports: 5001 .. 5010")
        sys.exit(1)
    
    port = int(sys.argv[1])
    if port not in list(range(5001, 5010)):
        print("Port must be between 5001 and 5010")
        sys.exit(1)
        
    main(port)