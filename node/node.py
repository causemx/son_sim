from node_base import Node
import sys
import time
import ipaddress

def main(ip, handler_ip='192.168.199.0'):
    # Create node with IP-based identification
    node = Node(ip=ip, handler_ip=handler_ip)
    
    # Register other possible nodes in network
    base_ip = '.'.join(ip.split('.')[:-1])  # Get network prefix (e.g., "192.168.199")
    for last_byte in range(1, 11):  # Nodes 1-10
        node_ip = f"{base_ip}.{last_byte}"
        if node_ip != ip:  # Don't register self
            node.register_node(ip=node_ip)
    
    # Start node
    node.start()
    
    print("\nNode started:")
    print(f"IP: {ip}")
    print(f"ID: {ip.split('.')[-1]}")  # ID is last byte of IP
    print(f"Handler: {handler_ip}\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node.stop()
        print(f"\nNode on IP {ip} stopped")

def validate_ip(ip):
    """Validate IP address format and range"""
    try:
        # Check if it's a valid IP address
        ipaddress.ip_address(ip)
        
        # Get the last byte and check range (1-10)
        last_byte = int(ip.split('.')[-1])
        if last_byte < 1 or last_byte > 10:
            print("Error: Last byte of IP must be between 1 and 10")
            return False
            
        return True
        
    except ValueError:
        print("Error: Invalid IP address format")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python node.py <ip>")
        print("Example: python node.py 192.168.199.1")
        print("Note: Last byte of IP (1-9) will be used as node ID")
        sys.exit(1)
    
    ip = sys.argv[1]
    if validate_ip(ip):
        main(ip)
    else:
        sys.exit(1)
