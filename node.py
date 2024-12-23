from node_base import Node, NodeType
import sys
import time

def main(ip_address):
    # Create node on a fixed port (e.g., 5000)
    node = Node(ip_address=ip_address, port=5000, node_type=NodeType.NODE)
    
    # Register monitor / gateway (using 192.168.199.0 as monitor IP)
    node.register_node(ip_address='192.168.199.0', port=5000, node_type=NodeType.MONITOR)
    
    # Register other possible nodes in the subnet
    # For example, registering nodes from 192.168.1.2 to 192.168.1.10
    base_ip = '.'.join(ip_address.split('.')[:-1])  # Get network prefix
    for last_byte in range(2, 11):
        other_ip = f"{base_ip}.{last_byte}"
        if other_ip != ip_address:  # Don't register self
            node.register_node(ip_address=other_ip, port=5000, node_type=NodeType.NODE)
    
    node.start()
    
    print(f"Node started on {ip_address} (ID: {int(ip_address.split('.')[-1])})")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node.stop()
        print(f"\nNode on {ip_address} stopped")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python node.py <ip_address>")
        print("Example: python node.py 192.168.1.5")
        sys.exit(1)
    
    ip_address = sys.argv[1]
    try:
        # Validate IP address format
        octets = ip_address.split('.')
        if len(octets) != 4 or not all(0 <= int(octet) <= 255 for octet in octets):
            raise ValueError("Invalid IP address format")
    except Exception:
        print("Invalid IP address format. Please use format: xxx.xxx.xxx.xxx")
        sys.exit(1)
        
    main(ip_address)