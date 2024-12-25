import socket
import threading
import time
import json
from enum import Enum

class NodeType(Enum):
    MONITOR = "MONITOR"
    NODE = "NODE"

class Node:
    def __init__(self, ip_address, port, node_type):
        self.ip_address = ip_address
        self.port = port
        self.node_id = int(ip_address.split('.')[-1])
        self.node_type = node_type
        self.nodes = {}  # {node_id: (ip_address, port, node_type)}
        self.master_id = None
        self.is_running = False
        self.election_in_progress = False
        self.last_heartbeat = {}
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((ip_address, self.port))
        self.is_master = False
        self.election_timeout = None
        self.heartbeat_count = {}  # Track consecutive heartbeats
        self.min_heartbeats = 3    # Number of consecutive heartbeats needed to confirm master
        self.heartbeat_interval = 1.0  # seconds
        self.heartbeat_timeout = 3.0   # seconds
        self.election_lock = threading.Lock()
        
    def start(self):
        self.is_running = True
        threading.Thread(target=self._handle_messages, daemon=True).start()
        
        if self.node_type == NodeType.NODE:
            threading.Thread(target=self._monitor_heartbeat, daemon=True).start()
            time.sleep(2)  # Wait for network stabilization
            self._start_election()

    def register_node(self, ip_address, port, node_type):
        node_id = int(ip_address.split('.')[-1])
        self.nodes[node_id] = (ip_address, port, node_type)

    def _send_message(self, to_node_id, message_type, data=None):
        if to_node_id in self.nodes:
            ip_address, port, _ = self.nodes[to_node_id]
            message = {
                'type': message_type,
                'from': self.node_id,
                'data': data or {}
            }
            try:
                self.socket.sendto(json.dumps(message).encode(), (ip_address, port))
            except Exception as e:
                print(f"Error sending message to {to_node_id}: {e}")

    def _broadcast_message(self, message_type, data=None):
        for node_id in self.nodes:
            if node_id != self.node_id:  # Don't send to self
                self._send_message(node_id, message_type, data)

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
        data = message['data']

        if msg_type == 'HEARTBEAT':
            self._handle_heartbeat(from_node)

        elif msg_type == 'ELECTION':
            with self.election_lock:
                if not self.election_in_progress:
                    self.election_in_progress = True
                    if self.node_id > from_node:
                        self._send_message(from_node, 'ELECTION_RESPONSE')
                        time.sleep(0.5)  # Small delay before starting new election
                        self._start_election()

        elif msg_type == 'ELECTION_RESPONSE':
            self.election_in_progress = False
            if self.election_timeout:
                self.election_timeout.cancel()

        elif msg_type == 'NEW_MASTER':
            new_master_id = data['master_id']
            self._handle_new_master(new_master_id)

    def _handle_heartbeat(self, from_node):
        """Handle received heartbeat with stability checks"""
        current_time = time.time()
        self.last_heartbeat[from_node] = current_time
        
        if from_node not in self.heartbeat_count:
            self.heartbeat_count[from_node] = 1
        else:
            self.heartbeat_count[from_node] += 1

        # Only update master if we've received enough consecutive heartbeats
        if self.heartbeat_count[from_node] >= self.min_heartbeats:
            if self.master_id != from_node:
                print(f"Node {self.node_id}: Confirmed new master {from_node} after {self.min_heartbeats} heartbeats")
                self.master_id = from_node
                self.is_master = False

    def _handle_new_master(self, new_master_id):
        """Handle new master announcement with stability checks"""
        self.master_id = new_master_id
        self.is_master = (self.node_id == new_master_id)
        self.election_in_progress = False
        self.heartbeat_count = {}  # Reset heartbeat counts
        
        if self.is_master:
            print(f"Node {self.node_id} becoming new master")
            threading.Thread(target=self._send_heartbeat, daemon=True).start()
        else:
            print(f"Node {self.node_id} acknowledging new master {new_master_id}")

    def _send_heartbeat(self):
        while self.is_running and self.is_master:
            try:
                self._broadcast_message('HEARTBEAT')
                time.sleep(self.heartbeat_interval)
            except Exception as e:
                print(f"Error sending heartbeat: {e}")

    def _monitor_heartbeat(self):
        while self.is_running:
            if not self.is_master and not self.election_in_progress:
                current_time = time.time()
                if (self.master_id is None or 
                    self.master_id not in self.last_heartbeat or 
                    current_time - self.last_heartbeat[self.master_id] > self.heartbeat_timeout):
                    
                    # Clear heartbeat counts when starting new election
                    self.heartbeat_count = {}
                    self._start_election()
                    
            time.sleep(1)

    def _start_election(self):
        with self.election_lock:
            if not self.election_in_progress:
                self.election_in_progress = True
                print(f"Node {self.node_id} starting election")
                self._broadcast_message('ELECTION')
                
                # Set timeout for election
                if self.election_timeout:
                    self.election_timeout.cancel()
                self.election_timeout = threading.Timer(2.0, self._election_timeout_handler)
                self.election_timeout.start()

    def _election_timeout_handler(self):
        """Handle election timeout - become master if no response received"""
        if self.election_in_progress:
            self.is_master = True
            self.master_id = self.node_id
            print(f"Node {self.node_id} becoming new master (election timeout)")
            self._broadcast_message('NEW_MASTER', {'master_id': self.node_id})
            threading.Thread(target=self._send_heartbeat, daemon=True).start()
            self.election_in_progress = False

    def stop(self):
        if self.node_type == NodeType.NODE:
            self._broadcast_message('NODE_SHUTDOWN')
        self.is_running = False
        if self.election_timeout:
            self.election_timeout.cancel()
        self.socket.close()