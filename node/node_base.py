import threading
import time
import json
from enum import Enum
from libs import drone_v2x
from libs.controller import DroneController

class NodeType(Enum):
    NODE = "NODE"

class JSONEncoder(json.JSONEncoder):
    """Extended JSON encoder that can handle custom objects"""
    
    def default(self, obj):
        # Handle Flight Mode enums
        if hasattr(obj, 'to_json'):
            return obj.to_json()
        # Handle enums
        elif isinstance(obj, Enum):
            return obj.value
        # Let the parent class handle other types or raise TypeError
        return super().default(obj)

class Node:
    def __init__(self, node_id):
        # Initialize with (group, id) addressing scheme
        self.group = 11  # Fixed group for all nodes (11)
        self.node_id = node_id
        self.handler_group = 1  # Handler's fixed group
        self.handler_id = 1     # Handler's fixed ID
        self.nodes = {}  # {node_id: (group, id)}
        self.master_id = None
        self.is_running = False
        self.is_master = False
        self.master_id = None

        # Initialize v2x communication
        drone_v2x.init()

        # Initialize drone controller
        self.drone_controller = DroneController(connection_string="udp:127.0.0.1:14650")
        self.drone_connected = False
        
        # Auto-connect attributes
        self.connection_attempts = 0
        self.max_connection_attempts = 10
        self.connection_retry_delay = 2  # seconds
        self.status_reporting = False
            
    def start(self):
        self.is_running = True
        threading.Thread(target=self._handle_messages, daemon=True).start()
        
        # Start auto-connect process
        threading.Thread(target=self._auto_connect, daemon=True).start()
        
        # Start heartbeat thread
        threading.Thread(target=self._send_heartbeat, daemon=True).start()
        print(f"Node {self.node_id} starting in initialization phase")
       
    def _auto_connect(self):
        """Automatic connection to drone with retry mechanism"""
        self.connection_attempts = 0
        connect_success = False
        
        print(f"Node {self.node_id}: Starting auto-connect process...")
        
        while self.is_running and self.connection_attempts < self.max_connection_attempts and not connect_success:
            self.connection_attempts += 1
            print(f"Node {self.node_id}: Connection attempt {self.connection_attempts} of {self.max_connection_attempts}")
            
            try:
                # Attempt to connect to drone
                connect_success = self.drone_controller.connect()
                
                if connect_success:
                    self.drone_connected = True
                    print(f"Node {self.node_id}: Successfully connected to drone")
                    
                    # Start status reporting
                    self._start_status_reporting()
                    
                    # Send NODE_ADDED message to handler now that we're connected
                    self._send_to_handler('NODE_ADDED', {'node_id': self.node_id})
                    print(f"Node {self.node_id}: Sent NODE_ADDED message to handler")
                    
                    break  # Exit the retry loop if successful
                else:
                    print(f"Node {self.node_id}: Connection attempt failed, retrying in {self.connection_retry_delay} seconds...")
                    time.sleep(self.connection_retry_delay)
            except Exception as e:
                print(f"Node {self.node_id}: Error during connection attempt: {e}")
                time.sleep(self.connection_retry_delay)
        
    def _start_status_reporting(self):
        """Start a thread to continuously send drone status to handler"""
        if not self.status_reporting:
            self.status_reporting = True
            self.status_thread = threading.Thread(target=self._status_reporter, daemon=True)
            self.status_thread.start()
            print(f"Node {self.node_id}: Started status reporting")

    def _stop_status_reporting(self):
        """Stop the status reporting thread"""
        if self.status_reporting:
            self.status_reporting = False
            if hasattr(self, 'status_thread'):
                self.status_thread.join(timeout=1.0)
            print(f"Node {self.node_id}: Stopped status reporting")

    def _status_reporter(self):
        """Thread function to continuously report drone status to handler"""
        while self.status_reporting and self.drone_connected and self.is_running:
            try:
                # Get comprehensive drone status
                status = self.drone_controller.get_drone_status()
                
                # Send status to handler
                self._send_to_handler('DRONE_STATUS_UPDATE', {
                    'status': status,
                    'timestamp': time.time()
                })
                
                # Wait for next report interval
                time.sleep(0.5)  # Report every 0.5 seconds
            except Exception as e:
                print(f"Error in status reporter: {e}")
                time.sleep(1)  # Prevent tight loop in case of errors

    def _send_to_handler(self, message_type, data=None):
        """Send message to handler using v2x communication"""
        message = {
            'type': message_type,
            'from': self.node_id,
            'data': data or {}
        }
        try:
            # Use the custom encoder to handle Enum values and other custom objects
            json_message = json.dumps(message, cls=JSONEncoder)
            # Send to handler with group 1, id 1
            drone_v2x.send(json_message, (self.handler_group, self.handler_id))
            print(f"Sent {message_type} to handler ({self.handler_group}, {self.handler_id})")
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
                    
                    # Start status reporting if connection successful
                    if success:
                        self._start_status_reporting()
                else:
                    result = {'success': True, 'message': 'Already connected'}
            
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
                # Ensure flight mode is serializable
                if hasattr(current_mode, 'value'):
                    mode_value = current_mode.value
                else:
                    mode_value = str(current_mode)
                    
                if current_mode:
                    result = {
                        'success': True,
                        'message': f'Current flight mode: {mode_value}',
                        'mode': mode_value
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
                
            elif command == 'disconnect':
                # Add a disconnect command to stop status reporting
                if self.drone_connected:
                    self._stop_status_reporting()
                    self.drone_controller.cleanup()
                    self.drone_connected = False
                    result = {'success': True, 'message': 'Disconnected successfully'}
                else:
                    result = {'success': False, 'message': 'Drone not connected'}

        except Exception as e:
            result = {'success': False, 'message': f'Error executing command: {str(e)}'}

        return result

    def _broadcast_to_nodes(self, message_type, data=None):
        """Broadcast message to all known nodes"""
        for node_id, (group, id) in self.nodes.items():
            message = {
                'type': message_type,
                'from': self.node_id,
                'data': data or {}
            }
            try:
                # Use the custom encoder for broadcasting
                json_message = json.dumps(message, cls=JSONEncoder)
                drone_v2x.send(json_message, (group, id))
                print(f"Broadcast {message_type} to node {node_id} ({group}, {id})")
            except Exception as e:
                print(f"Error broadcasting to node {node_id}: {e}")

    def _handle_messages(self):
        while self.is_running:
            try:
                data, addr = drone_v2x.recv(1400)
                # Parse received JSON data
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
                # Ensure flight mode is serializable
                mode = self.drone_controller.flight_mode
                if hasattr(mode, 'value'):
                    mode_value = mode.value
                else:
                    mode_value = str(mode)
                    
                status_data = {
                    'armed': self.drone_controller.is_armed,
                    'mode': mode_value,
                    'altitude': self.drone_controller.altitude
                }
            
            self._send_to_handler(heartbeat_type, status_data)
            time.sleep(1)

    def register_node(self, node_id):
        """Register another node using node ID"""
        # All nodes are in group 11
        self.nodes[node_id] = (self.group, node_id)

    def stop(self):
        if self.is_running:
            if self.drone_connected:
                self._stop_status_reporting()
                self.drone_controller.cleanup()
            self._send_to_handler('NODE_SHUTDOWN')
        self.is_running = False