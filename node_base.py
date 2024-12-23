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
        # Extract last byte of IP address as node_id
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
        
    def start(self):
        self.is_running = True
        threading.Thread(target=self._handle_messages, daemon=True).start()
        
        if self.node_type == NodeType.NODE:
            threading.Thread(target=self._monitor_heartbeat, daemon=True).start()
            # Initial election when node starts
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
            self.socket.sendto(json.dumps(message).encode(), (ip_address, port))

    def _broadcast_message(self, message_type, data=None):
        for node_id in self.nodes:
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
            self.last_heartbeat[from_node] = time.time()
            self.master_id = from_node

        elif msg_type == 'ELECTION':
            if not self.election_in_progress:
                self.election_in_progress = True
                # Compare node_ids (last byte of IP)
                if self.node_id > from_node:
                    self._send_message(from_node, 'ELECTION_RESPONSE')
                    self._start_election()

        elif msg_type == 'ELECTION_RESPONSE':
            self.election_in_progress = False

        elif msg_type == 'NEW_MASTER':
            new_master_id = data['master_id']
            self.master_id = new_master_id
            self.is_master = (self.node_id == new_master_id)
            if self.is_master:
                threading.Thread(target=self._send_heartbeat, daemon=True).start()
            self.election_in_progress = False

    def _send_heartbeat(self):
        while self.is_running and self.is_master:
            self._broadcast_message('HEARTBEAT')
            time.sleep(1)

    def _monitor_heartbeat(self):
        while self.is_running:
            if not self.is_master:  # Only non-masters monitor heartbeat
                if (self.master_id is None or 
                    self.master_id not in self.last_heartbeat or 
                    time.time() - self.last_heartbeat[self.master_id] > 3):
                    self._start_election()
            time.sleep(1)

    def _start_election(self):
        if not self.election_in_progress:
            self.election_in_progress = True
            print(f"Node {self.node_id} starting election")
            self._broadcast_message('ELECTION')
            time.sleep(2)
            
            if self.election_in_progress:  # No higher IP responded
                self.is_master = True
                self.master_id = self.node_id
                print(f"Node {self.node_id} becoming new master")
                self._broadcast_message('NEW_MASTER', {'master_id': self.node_id})
                threading.Thread(target=self._send_heartbeat, daemon=True).start()

    def stop(self):
        self.is_running = False
        self.socket.close()