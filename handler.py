from node_base import Node, NodeType
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
    def __init__(self, handler_host='0.0.0.0', handler_port=5566, gui_host='remote_gui_ip', gui_port=5567):
        self.handler_host = handler_host
        self.handler_port = handler_port
        self.gui_host = gui_host
        self.gui_port = gui_port
        self.monitor_node = None
        self.is_running = False
        self.known_nodes = set()
        
        # Setup UDP socket for GUI communication
        self.gui_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.gui_socket.bind((handler_host, handler_port))
        logging.info(f"Network handler initialized on {handler_host}:{handler_port}")
        logging.info(f"Connected to GUI at {gui_host}:{gui_port}")

    def send_to_gui(self, message_type, data):
        message = {
            'type': message_type,
            'data': data
        }
        try:
            msg_json = json.dumps(message)
            self.gui_socket.sendto(
                msg_json.encode(),
                (self.gui_host, self.gui_port)
            )
            logging.info(f"OUT -> GUI [{message_type}]: {json.dumps(data, indent=2)}")
        except Exception as e:
            logging.error(f"Error sending to GUI: {e}")

    def process_node_message(self, message):
        msg_type = message['type']
        from_node = message['from']
        data = message.get('data', {})
        
        # Log incoming message
        logging.info(f"IN  <- Node {from_node} [{msg_type}]: {json.dumps(data, indent=2)}")
        
        if from_node not in self.known_nodes:
            self.known_nodes.add(from_node)
            logging.info(f"New node joined: Node {from_node} (Port {5000 + from_node})")
            self.send_to_gui('NODE_ADDED', {
                'port': 5000 + from_node,
                'node_type': 'NODE'
            })
            self.send_to_gui('LOG', {
                'message': f"Node {from_node} (Port {5000 + from_node}) joined network"
            })
        
        if msg_type == 'HEARTBEAT':
            logging.debug(f"Heartbeat received from Node {from_node}")
            self.send_to_gui('MASTER_CHANGED', {
                'master_id': from_node
            })
        elif msg_type == 'ELECTION':
            logging.info(f"Election process started by Node {from_node}")
            self.send_to_gui('LOG', {
                'message': "Election process started"
            })
        elif msg_type == 'NEW_MASTER':
            new_master = message['data']['master_id']
            logging.info(f"Node {new_master} elected as new master")
            self.send_to_gui('LOG', {
                'message': f"Node {new_master} became master"
            })
            self.send_to_gui('MASTER_CHANGED', {
                'master_id': new_master
            })
        elif msg_type == 'ELECTION_RESPONSE':
            logging.info(f"Election response received from Node {from_node}")

    def monitor_nodes(self):
        while self.is_running:
            time.sleep(1)
            current_time = time.time()
            for node_id in self.known_nodes:
                if node_id != 0:  # Skip monitor node
                    if node_id in self.monitor_node.last_heartbeat:
                        last_seen = self.monitor_node.last_heartbeat[node_id]
                        time_diff = current_time - last_seen
                        if time_diff > 3:
                            logging.warning(f"Node {node_id} became inactive (no heartbeat for {time_diff:.1f}s)")
                            self.send_to_gui('NODE_STATUS', {
                                'node_id': node_id,
                                'status': "Inactive"
                            })
                            self.send_to_gui('LOG', {
                                'message': f"Node {node_id} became inactive"
                            })
                        elif self.monitor_node.nodes.get(node_id, {}).get("status") == "Inactive":
                            logging.info(f"Node {node_id} became active again")
                            self.send_to_gui('NODE_STATUS', {
                                'node_id': node_id,
                                'status': "Active"
                            })
                            self.send_to_gui('LOG', {
                                'message': f"Node {node_id} became active"
                            })

    def start(self):
        # Initialize and start monitor node
        self.monitor_node = Node(5000, NodeType.MONITOR)
        # Override the process_message method to add logging
        original_process = self.monitor_node._process_message
        def logged_process(message):
            # Log the raw message received by the monitor node
            logging.info(f"RAW <- Port {message.get('from', 'unknown')}: {json.dumps(message, indent=2)}")
            return original_process(message)
        self.monitor_node._process_message = self.process_node_message
        self.monitor_node.start()
        logging.info("Monitor node started on port 5000")
        
        # Add monitor node to known nodes
        self.known_nodes.add(0)
        self.send_to_gui('NODE_ADDED', {
            'port': 5000,
            'node_type': "MONITOR"
        })
        
        # Start monitoring thread
        self.is_running = True
        threading.Thread(target=self.monitor_nodes, daemon=True).start()
        logging.info("Node monitoring thread started")

    def stop(self):
        self.is_running = False
        if self.monitor_node:
            self.monitor_node.stop()
        self.gui_socket.close()
        logging.info("Network handler stopped")

def main():
    logging.info("Starting network handler...")
    handler = NetworkHandler()
    handler.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down network handler...")
        handler.stop()
        print("\nHandler stopped")

if __name__ == "__main__":
    main()