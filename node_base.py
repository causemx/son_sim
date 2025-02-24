import socket
import threading
import time
import json
from enum import Enum

class NodeType(Enum):
    NODE = "NODE"

class Node:
    def __init__(self, ip, handler_ip='192.168.199.0', handler_port=5000):
        self.ip = ip
        self.port = 5000  # Fixed port for all nodes
        self.node_id = int(ip.split('.')[-1])  # Use last byte of IP as node ID
        self.host = ip
        self.handler_ip = handler_ip
        self.handler_port = handler_port
        self.nodes = {}  # {node_id: (host_ip, port)}
        self.master_id = None
        self.is_running = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((ip, self.port))
        self.is_master = False
        self.master_id = None
            
    def start(self):
        self.is_running = True
        threading.Thread(target=self._handle_messages, daemon=True).start()
        
        # Broadcast initial message to handler
        self._send_to_handler('NODE_ADDED', {'node_id': self.node_id})
        
        # Start heartbeat thread
        threading.Thread(target=self._send_heartbeat, daemon=True).start()
        print(f"Node {self.node_id} starting in initialization phase")
       

    def _send_to_handler(self, message_type, data=None):
        """Send message to handler"""
        message = {
            'type': message_type,
            'from': self.node_id,
            'data': data or {}
        }
        try:
            self.socket.sendto(
                json.dumps(message).encode(),
                (self.handler_ip, self.handler_port)
            )
        except Exception as e:
            print(f"Error sending to handler: {e}")

    def _broadcast_to_nodes(self, message_type, data=None):
        """Broadcast message to all known nodes"""
        for node_id, (host, port) in self.nodes.items():
            message = {
                'type': message_type,
                'from': self.node_id,
                'data': data or {}
            }
            try:
                self.socket.sendto(json.dumps(message).encode(), (host, port))
            except Exception as e:
                print(f"Error broadcasting to node {node_id}: {e}")

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

        if msg_type == 'NEW_MASTER':
            new_master_id = data['master_id']
            self.master_id = new_master_id
            self.is_master = (self.node_id == new_master_id)
            if self.is_master:
                print(f"Node {self.node_id} selected as master")
            else:
                print(f"Node {self.node_id} acknowledging Node {new_master_id} as master")

    def _send_heartbeat(self):
        """Send heartbeat messages to handler"""
        while self.is_running:
            # Master sends MASTER_HEARTBEAT, regular nodes send NODE_HEARTBEAT
            heartbeat_type = 'MASTER_HEARTBEAT' if self.is_master else 'NODE_HEARTBEAT'
            self._send_to_handler(heartbeat_type)
            time.sleep(1)

    def register_node(self, ip):
        """Register another node using IP"""
        node_id = int(ip.split('.')[-1])
        self.nodes[node_id] = (ip, self.port)

    def stop(self):
        if self.is_running:
            self._send_to_handler('NODE_SHUTDOWN')
        self.is_running = False
        self.socket.close()