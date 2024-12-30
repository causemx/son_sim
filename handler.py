import sys
import socket
import json
import time
import threading
import logging

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class NetworkHandler:
    def __init__(self, mesh_ip='192.168.199.0', outside_ip='192.168.1.2'):
        # Mesh network interface (for nodes)
        self.mesh_host = mesh_ip
        self.mesh_port = 5000
        
        # Outside network interface (for GUI)
        self.outside_host = outside_ip
        self.outside_port = 5567  # Port for receiving GUI messages
        self.gui_host = '192.168.1.1'  # GUI's outside IP
        self.gui_port = 5567  # GUI's port
        
        self.is_running = False
        self.known_nodes = set()
        self.master_id = 1
        
        # Setup socket for node communication (mesh network)
        self.node_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.node_socket.bind((self.mesh_host, self.mesh_port))
            self.node_socket.settimeout(0.1)
            logging.info(f"Handler bound to mesh network: {self.mesh_host}:{self.mesh_port}")
        except socket.error as e:
            logging.error(f"Failed to bind mesh network socket: {e}")
            raise

        # Setup socket for GUI communication (outside network)
        self.gui_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.gui_socket.bind((self.outside_host, self.outside_port))
            self.gui_socket.settimeout(0.1)
            logging.info(f"Handler bound to outside network: {self.outside_host}:{self.outside_port}")
        except socket.error as e:
            logging.error(f"Failed to bind outside network socket: {e}")
            raise

        logging.info("Network handler initialized")
        logging.info(f"GUI communication configured for {self.gui_host}:{self.gui_port}")

    def send_to_gui(self, message_type, data):
        message = {
            'type': message_type,
            'data': data
        }
        try:
            self.gui_socket.sendto(
                json.dumps(message).encode(),
                (self.gui_host, self.gui_port)
            )
        except Exception as e:
            logging.error(f"Error sending to GUI: {e}")

    def send_network_state(self):
        """Send current network state to GUI"""
        time.sleep(0.5)  # Short delay to ensure GUI is ready
        
        # Send all known nodes
        for node_id in self.known_nodes:
            self.send_to_gui('NODE_ADDED', {
                'port': 5000 + node_id,
                'node_type': 'NODE'
            })
        
        # Send current master status
        if self.master_id is not None:
            self.send_to_gui('MASTER_CHANGED', {
                'master_id': self.master_id
            })
            
        logging.info(f"Sent network state: nodes={self.known_nodes}, master={self.master_id}")

    def process_node_message(self, message, addr):
        msg_type = message['type']
        from_node = message['from']  # This is now the node_id from last byte of IP
        data = message.get('data', {})
        
        logging.info(f"IN  <- Node {from_node} [{msg_type}]: {json.dumps(data, indent=2)}")
        
        # Handle new node registration
        if from_node not in self.known_nodes:
            self.known_nodes.add(from_node)
            logging.info(f"New node joined: Node {from_node} (IP .{from_node})")
            
            # Send node addition to GUI
            self.send_to_gui('NODE_ADDED', {
                'ip_last_byte': from_node,
                'node_type': 'NODE'
            })
            
            # Send log message
            self.send_to_gui('LOG', {
                'message': f"Node {from_node} (IP .{from_node}) joined network"
            })
            
            # If this has lowest IP last byte, make it master immediately
            if from_node == 1:
                self.master_id = 1
                self.send_to_gui('MASTER_CHANGED', {
                    'master_id': 1
                })
        
        # Handle different message types
        if msg_type == 'NODE_SHUTDOWN':
            if from_node in self.known_nodes:
                self.known_nodes.remove(from_node)
                self.send_to_gui('NODE_REMOVED', {
                    'node_id': from_node
                })
                
                # If master node was removed, notify GUI
                if from_node == self.master_id:
                    self.master_id = None
                    logging.info("Master node removed - waiting for new election")
        
        elif msg_type == 'HEARTBEAT':
            if from_node == self.master_id:
                self.send_to_gui('MASTER_CHANGED', {
                    'master_id': from_node
                })
            
        elif msg_type == 'ELECTION':
            logging.info(f"Election process started by Node {from_node}")
            self.send_to_gui('LOG', {
                'message': "Election process started"
            })
            
        elif msg_type == 'MASTER_LOST':
            lost_master = data['lost_master_id']
            if lost_master == self.master_id:
                self.master_id = None
                logging.info(f"Master node {lost_master} lost - heartbeat timeout")
                self.send_to_gui('LOG', {
                    'message': f"Master node {lost_master} lost - heartbeat timeout"
                })
                self.send_to_gui('NODE_REMOVED', {
                    'node_id': lost_master
                })
                # Clear master status in GUI
                self.send_to_gui('MASTER_CHANGED', {
                    'master_id': None
                })

        elif msg_type == 'NEW_MASTER':
            new_master = data['master_id']
            self.master_id = new_master
            logging.info(f"Node {self.master_id} elected as new master")
            self.send_to_gui('LOG', {
                'message': f"Node {self.master_id} became master"
            })
            self.send_to_gui('MASTER_CHANGED', {
                'master_id': self.master_id
            })

    def run(self):
        self.is_running = True
        
        while self.is_running:
            try:
                # Check for node messages (mesh network)
                try:
                    data, addr = self.node_socket.recvfrom(1024)
                    message = json.loads(data.decode())
                    
                    if message['type'] == 'GUI_CONNECTED':
                        logging.info("GUI connected - sending network state")
                        self.send_network_state()
                    else:
                        self.process_node_message(message, addr)
                except socket.timeout:
                    pass
                
                # Check for GUI messages (outside network)
                try:
                    data, addr = self.gui_socket.recvfrom(1024)
                    message = json.loads(data.decode())
                    if message['type'] == 'GUI_CONNECTED':
                        logging.info("GUI connected - sending network state")
                        self.send_network_state()
                except socket.timeout:
                    pass
                    
            except Exception as e:
                logging.error(f"Error processing message: {e}")
            
            time.sleep(0.1)

    def start(self):
        # Start main processing thread
        threading.Thread(target=self.run, daemon=True).start()
        logging.info("Network handler started")

    def stop(self):
        self.is_running = False
        self.node_socket.close()
        self.gui_socket.close()
        logging.info("Network handler stopped")

def main():
    logging.info("Starting network handler...")
    try:
        handler = NetworkHandler(
            mesh_ip='192.168.199.0',    # Mesh network IP
            outside_ip='192.168.1.2'    # Outside network IP
        )
        handler.start()
        
        print("\nHandler running on two interfaces:")
        print(f"Mesh network: {handler.mesh_host}:{handler.mesh_port}")
        print(f"Outside network: {handler.outside_host}:{handler.outside_port}")
        print(f"Sending GUI updates to {handler.gui_host}:{handler.gui_port}")
        print("\nPress Ctrl+C to stop")
        
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handler.stop()
        print("\nHandler stopped")
    except Exception as e:
        logging.error(f"Error running handler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()