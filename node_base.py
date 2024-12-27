import socket
import threading
import time
import json
from enum import Enum

class NodeType(Enum):
    NODE = "NODE"


class Node:
    def __init__(self, port, handler_port=5000, host='localhost'):
        self.port = port
        self.node_id = port % 1000  # Convert port to node_id (e.g., 5001 -> 1)
        self.host = host
        self.handler_port = handler_port
        self.nodes = {}  # {node_id: (host, port)}
        self.master_id = None
        self.is_running = False
        self.election_in_progress = False
        self.last_heartbeat = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host, self.port))
        self.is_master = False
        
        # Node 1 is default master
        if self.node_id == 1:
            self.is_master = True
            self.master_id = self.node_id
            
    def start(self):
        self.is_running = True
        threading.Thread(target=self._handle_messages, daemon=True).start()
        
        # Broadcast initial message to handler
        self._send_to_handler('NODE_ADDED', {'node_id': self.node_id})
        
        # Start heartbeat monitoring for all nodes
        threading.Thread(target=self._monitor_heartbeat, daemon=True).start()
        
        # If Node 1, start as master
        if self.node_id == 1:
            threading.Thread(target=self._send_heartbeat, daemon=True).start()
            print(f"Node {self.node_id} starting as master")
        else:
            print(f"Node {self.node_id} starting as regular node")

    def _send_to_handler(self, message_type, data=None):
        """Send message to handler"""
        message = {
            'type': message_type,
            'from': self.node_id,
            'data': data or {}
        }
        self.socket.sendto(
            json.dumps(message).encode(),
            (self.host, self.handler_port)
        )

    def _broadcast_to_nodes(self, message_type, data=None):
        """Broadcast message to all known nodes"""
        for node_id, (host, port) in self.nodes.items():
            message = {
                'type': message_type,
                'from': self.node_id,
                'data': data or {}
            }
            self.socket.sendto(json.dumps(message).encode(), (host, port))

    def _handle_messages(self):
        while self.is_running:
            try:
                data, addr = self.socket.recvfrom(1024)
                message = json.loads(data.decode())
                self._process_message(message)
            except Exception as e:
                print(f"Error handling message: {e}")

    def _process_message(self, message):
        msg_type = message['type']
        from_node = message['from']
        data = message.get('data', {})

        if msg_type == 'HEARTBEAT':
            self.last_heartbeat[from_node] = time.time()
            self.master_id = from_node

        elif msg_type == 'ELECTION':
            # Only participate in election if master is gone
            if not self.election_in_progress and self.master_id is None:
                self.election_in_progress = True
                if self.node_id > from_node:
                    self._broadcast_to_nodes('ELECTION_RESPONSE')
                    self._start_election()

        elif msg_type == 'ELECTION_RESPONSE':
            self.election_in_progress = False

        elif msg_type == 'NEW_MASTER':
            new_master_id = data['master_id']
            self.master_id = new_master_id
            self.is_master = (self.node_id == new_master_id)
            self.election_in_progress = False

    def _send_heartbeat(self):
        while self.is_running and self.is_master:
            self._send_to_handler('HEARTBEAT')
            self._broadcast_to_nodes('HEARTBEAT')
            time.sleep(1)

    def _monitor_heartbeat(self):
        while self.is_running:
            if not self.is_master and self.master_id is not None:
                if (self.master_id not in self.last_heartbeat or 
                    time.time() - self.last_heartbeat[self.master_id] > 3):
                    print(f"Node {self.node_id}: Master {self.master_id} heartbeat lost")
                    # Notify handler about lost master
                    self._send_to_handler('MASTER_LOST', {'lost_master_id': self.master_id})
                    # Clear master info
                    self.master_id = None
                    # Start election
                    self._start_election()
            time.sleep(1)

    def _start_election(self):
        if not self.election_in_progress:
            self.election_in_progress = True
            print(f"Node {self.node_id} starting election")
            self._broadcast_to_nodes('ELECTION')
            time.sleep(2)
            
            if self.election_in_progress:  # No higher ID responded
                self.is_master = True
                self.master_id = self.node_id
                print(f"Node {self.node_id} becoming new master")
                data = {'master_id': self.node_id}
                self._send_to_handler('NEW_MASTER', data)
                self._broadcast_to_nodes('NEW_MASTER', data)
                threading.Thread(target=self._send_heartbeat, daemon=True).start()

    def register_node(self, port, host='localhost'):
        """Register another node"""
        node_id = port % 1000
        self.nodes[node_id] = (host, port)

    def stop(self):
        if self.is_running:
            self._send_to_handler('NODE_SHUTDOWN')
        self.is_running = False
        self.socket.close()