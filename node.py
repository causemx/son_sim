from node_base import Node
import sys
import time
import ipaddress


def main(ip):
    # Create node
    node = Node(ip=ip)
    
    # Register other possible nodes
    base_ip = '.'.join(ip.split('.')[:-1])  # Get network prefix
    for last_byte in range(1, 10):
        node_ip = f"{base_ip}.{last_byte}"
        if node_ip != ip:  # Don't register self
            node.register_node(ip=node_ip)
    
    node.start()
    
    print(f"Node started on IP {ip} (ID: {ip.split('.')[-1]})")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node.stop()
        print(f"\nNode on IP {ip} stopped")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python node.py <ip>")
        print("Example: python node.py 192.168.199.__")
        sys.exit(1)
    
    ip = sys.argv[1]
    try:
        # Validate IP address
        ipaddress.ip_address(ip)
        main(ip)
    except ValueError:
        print("Invalid IP address format")
        sys.exit(1)