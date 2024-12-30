from node_base import Node
import sys
import time
import ipaddress

def main(ip, handler_ip='192.168.199.0'):
    # Create node with handler IP
    node = Node(ip=ip, handler_ip=handler_ip)
    
    # Register other possible nodes
    base_ip = '.'.join(ip.split('.')[:-1])
    for last_byte in range(1, 10):
        node_ip = f"{base_ip}.{last_byte}"
        if node_ip != ip:
            node.register_node(ip=node_ip)
    
    node.start()
    
    print(f"Node started on IP {ip} (ID: {ip.split('.')[-1]})")
    print(f"Sending messages to handler at {handler_ip}:5000")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node.stop()
        print(f"\nNode on IP {ip} stopped")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python node.py <ip>")
        print("Example: python node.py 192.168.199.1")
        sys.exit(1)
    
    ip = sys.argv[1]
    try:
        ipaddress.ip_address(ip)
        main(ip)
    except ValueError:
        print("Invalid IP address format")
        sys.exit(1)