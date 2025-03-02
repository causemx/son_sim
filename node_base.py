import socket
import threading
import time
import json
from enum import Enum
from controller import DroneController

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

         # Initialize drone controller
        self.drone_controller = DroneController(connection_string="udp:127.0.0.1:14550")
        self.drone_connected = False
            
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

    def _handle_drone_command(self, command, params=None):
        """Handle drone commands and return result"""
        result = {
            'success': False,
            'message': ''
        }

        try:
            if command == 'connect':
                if not self.drone_connected:
                    success = self.drone_controller.connect()
                    self.drone_connected = success
                    result = {'success': success, 'message': 'Connected successfully' if success else 'Connection failed'}
            
            elif not self.drone_connected:
                return {'success': False, 'message': 'Drone not connected'}
            
            elif command == 'arm':
                result = {'success': self.drone_controller.arm(), 'message': 'Armed successfully'}
            
            elif command == 'disarm':
                result = {'success': self.drone_controller.disarm(), 'message': 'Disarmed successfully'}
            
            elif command == 'takeoff':
                if params and 'altitude' in params:
                    altitude = float(params['altitude'])
                    result = {
                        'success': self.drone_controller.takeoff(altitude),
                        'message': f'Takeoff command sent - target altitude: {altitude}m'
                    }
                else:
                    result = {'success': False, 'message': 'Altitude parameter required'}
            
            elif command == 'set_mode':
                if params and 'mode' in params:
                    mode = params['mode']
                    result = {
                        'success': self.drone_controller.set_flight_mode(mode),
                        'message': f'Flight mode set to {mode}'
                    }
                else:
                    result = {'success': False, 'message': 'Mode parameter required'}
            
            elif command == 'set_throttle':
                if params and 'value' in params:
                    value = int(params['value'])
                    result = {
                        'success': self.drone_controller.set_throttle(value),
                        'message': f'Throttle set to {value}%'
                    }
                else:
                    result = {'success': False, 'message': 'Throttle value required'}
                    
            elif command == 'get_mode':
                # New command to get current flight mode
                current_mode = self.drone_controller.get_current_mode()
                if current_mode:
                    result = {
                        'success': True,
                        'message': f'Current flight mode: {current_mode}',
                        'mode': current_mode
                    }
                else:
                    result = {'success': False, 'message': 'Could not retrieve flight mode'}
                    
            elif command == 'get_status':
                # Get comprehensive drone status
                status = self.drone_controller.get_drone_status()
                result = {
                    'success': True,
                    'message': 'Status retrieved successfully',
                    'status': status
                }

        except Exception as e:
            result = {'success': False, 'message': f'Error executing command: {str(e)}'}

        return result


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

        elif msg_type == 'DRONE_COMMAND':
            command = data.get('command')
            params = data.get('params')
            
            # Execute drone command and get result
            result = self._handle_drone_command(command, params)
            
            # Send acknowledgment back to handler
            self._send_to_handler('COMMAND_ACK', {
                'command': command,
                'result': result,
                'timestamp': time.time()
            })

    def _send_heartbeat(self):
        """Send heartbeat messages to handler"""
        while self.is_running:
            # Master sends MASTER_HEARTBEAT, regular nodes send NODE_HEARTBEAT
            heartbeat_type = 'MASTER_HEARTBEAT' if self.is_master else 'NODE_HEARTBEAT'
            
            # Include drone status in heartbeat if connected
            status_data = {}
            if self.drone_connected:
                status_data = {
                    'armed': self.drone_controller.is_armed,
                    'mode': self.drone_controller.flight_mode,
                    'altitude': self.drone_controller.altitude
                }
            
            self._send_to_handler(heartbeat_type, status_data)
            time.sleep(1)

    def register_node(self, ip):
        """Register another node using IP"""
        node_id = int(ip.split('.')[-1])
        self.nodes[node_id] = (ip, self.port)

    def stop(self):
        if self.is_running:
            if self.drone_connected:
                self.drone_controller.cleanup()
            self._send_to_handler('NODE_SHUTDOWN')
        self.is_running = False
        self.socket.close()