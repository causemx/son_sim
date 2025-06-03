import statistics
import sys
import json
import time
import threading
import logging
import atexit
import os
from enum import Enum
from libs import drone_v2x
from libs.controller import DroneController

# Add terminal reset function that will run on exit
def reset_terminal():
    os.system('stty echo')   # Re-enable terminal echo
    os.system('stty sane')   # Reset terminal to sane state

# Register the reset function to run when program exits
atexit.register(reset_terminal)

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

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

class NetworkHandler:
    def __init__(self, handler_id=11, gui_group=1, gui_id=1):
        # V2X communication settings - Handler now in Group 1
        self.group = 1  # Handler's group (changed from 11 to 1)
        self.handler_id = handler_id  # Handler's ID (default is 11)
        self.node_group = 11  # Nodes are in group 11
        
        # GUI communication settings
        self.gui_group = gui_group  # GUI's group
        self.gui_id = gui_id  # GUI's ID

        self.is_running = False
        self.known_nodes = set()
        self.master_id = None  # Initialize with no master
        self.last_network_change = time.time()

        # Node health tracking
        self.last_heartbeat = {}
        self.heartbeat_timeout = 6  # Seconds before considering a node dead

        # Initialization phase attributes
        self.initialization_phase = True
        self.expected_nodes = 2  # Expecting nodes 13 and 14
        self.node_scores = {}
        self.join_timestamps = {}
        self.heartbeat_consistency = {}
        self.heartbeat_window_size = 10

        # Command response tracking
        self.command_responses = {}

        # Initialize drone controller (similar to node)
        self.drone_controller = DroneController(connection_string="udp:127.0.0.1:14550")  # Different port from nodes
        self.drone_connected = False
        
        # Auto-connect attributes
        self.connection_attempts = 0
        self.max_connection_attempts = 10
        self.connection_retry_delay = 2  # seconds
        self.status_reporting = False

        # Initialize drone_v2x
        try:
            drone_v2x.init()
            logging.info(f"Handler initialized with V2X communication - Group {self.group}, ID {self.handler_id}")
        except Exception as e:
            logging.error(f"Failed to initialize V2X communication: {e}")
            raise

        logging.info("Network handler initialized")
        logging.info(f"GUI communication configured for Group {self.gui_group}, ID {self.gui_id}")

    def _auto_connect(self):
        """Automatic connection to drone with retry mechanism (similar to node)"""
        self.connection_attempts = 0
        connect_success = False
        
        print(f"Handler {self.handler_id}: Starting auto-connect process...")
        
        while self.is_running and self.connection_attempts < self.max_connection_attempts and not connect_success:
            self.connection_attempts += 1
            print(f"Handler {self.handler_id}: Connection attempt {self.connection_attempts} of {self.max_connection_attempts}")
            
            try:
                # Attempt to connect to drone
                connect_success = self.drone_controller.connect()
                
                if connect_success:
                    self.drone_connected = True
                    print(f"Handler {self.handler_id}: Successfully connected to drone")
                    
                    # Start status reporting
                    self._start_status_reporting()
                    
                    # Send log to GUI about successful connection
                    self.send_to_gui('LOG', {
                        'message': f"Handler {self.handler_id}: Successfully connected to drone"
                    })
                    
                    break  # Exit the retry loop if successful
                else:
                    print(f"Handler {self.handler_id}: Connection attempt failed, retrying in {self.connection_retry_delay} seconds...")
                    time.sleep(self.connection_retry_delay)
            except Exception as e:
                print(f"Handler {self.handler_id}: Error during connection attempt: {e}")
                time.sleep(self.connection_retry_delay)
        
        if not connect_success:
            print(f"Handler {self.handler_id}: Failed to connect to drone after {self.max_connection_attempts} attempts")
            self.send_to_gui('LOG', {
                'message': f"Handler {self.handler_id}: Failed to connect to drone after {self.max_connection_attempts} attempts",
                'level': 'error'
            })

    def _start_status_reporting(self):
        """Start a thread to continuously send drone status to GUI"""
        if not self.status_reporting:
            self.status_reporting = True
            self.status_thread = threading.Thread(target=self._status_reporter, daemon=True)
            self.status_thread.start()
            print(f"Handler {self.handler_id}: Started status reporting")

    def _stop_status_reporting(self):
        """Stop the status reporting thread"""
        if self.status_reporting:
            self.status_reporting = False
            if hasattr(self, 'status_thread'):
                self.status_thread.join(timeout=1.0)
            print(f"Handler {self.handler_id}: Stopped status reporting")

    def _status_reporter(self):
        """Thread function to continuously report handler's drone status to GUI"""
        while self.status_reporting and self.drone_connected and self.is_running:
            try:
                # Get comprehensive drone status
                status = self.drone_controller.get_drone_status()
                
                # Send status to GUI as a special handler status update
                gui_status_data = {
                    'node_id': self.handler_id,
                    'is_master': False,  # Handler is not part of master election
                    'is_handler': True,  # Mark as handler
                    'armed': status.get('armed', False),
                    'flight_mode': status.get('mode', 'UNKNOWN'),
                    'altitude': status.get('altitude', 0),
                    'position': status.get('position', None),
                    'heading': status.get('heading', None),
                    'groundspeed': status.get('groundspeed', None),
                    'gps': status.get('gps', None),
                    'battery': status.get('battery', None),
                    'system_status': status.get('system_status', None),
                    'timestamp': time.time()
                }

                self.send_to_gui('DRONE_STATUS_UPDATE', gui_status_data)
                
                # Wait for next report interval
                time.sleep(0.5)  # Report every 0.5 seconds
            except Exception as e:
                print(f"Error in handler status reporter: {e}")
                time.sleep(1)  # Prevent tight loop in case of errors

    def _handle_handler_drone_command(self, command, params=None):
        """Handle drone commands for the handler's own drone"""
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
                return {'success': False, 'message': 'Handler drone not connected'}
            
            elif command == 'arm':
                result = {'success': self.drone_controller.arm(), 'message': 'Handler drone armed successfully'}
            
            elif command == 'disarm':
                result = {'success': self.drone_controller.disarm(), 'message': 'Handler drone disarmed successfully'}
            
            elif command == 'takeoff':
                if params and 'altitude' in params:
                    altitude = float(params['altitude'])
                    result = {
                        'success': self.drone_controller.takeoff(altitude),
                        'message': f'Handler drone takeoff command sent - target altitude: {altitude}m'
                    }
                else:
                    result = {'success': False, 'message': 'Altitude parameter required'}
            
            elif command == 'set_mode':
                if params and 'mode' in params:
                    mode = params['mode']
                    result = {
                        'success': self.drone_controller.set_flight_mode(mode),
                        'message': f'Handler drone flight mode set to {mode}'
                    }
                else:
                    result = {'success': False, 'message': 'Mode parameter required'}
            
            elif command == 'get_mode':
                current_mode = self.drone_controller.get_current_mode()
                if hasattr(current_mode, 'value'):
                    mode_value = current_mode.value
                else:
                    mode_value = str(current_mode)
                    
                if current_mode:
                    result = {
                        'success': True,
                        'message': f'Handler drone current flight mode: {mode_value}',
                        'mode': mode_value
                    }
                else:
                    result = {'success': False, 'message': 'Could not retrieve handler drone flight mode'}
                    
            elif command == 'get_status':
                status = self.drone_controller.get_drone_status()
                result = {
                    'success': True,
                    'message': 'Handler drone status retrieved successfully',
                    'status': status
                }
                
            elif command == 'disconnect':
                if self.drone_connected:
                    self._stop_status_reporting()
                    self.drone_controller.cleanup()
                    self.drone_connected = False
                    result = {'success': True, 'message': 'Handler drone disconnected successfully'}
                else:
                    result = {'success': False, 'message': 'Handler drone not connected'}

        except Exception as e:
            result = {'success': False, 'message': f'Error executing handler drone command: {str(e)}'}

        return result

    def assign_new_master(self):
        """Assign the node with next smallest ID as the new master after network stabilization"""
        if not self.known_nodes:
            self.master_id = None
            logging.info("No nodes available in network")
            self.send_to_gui('LOG', {
                'message': "No nodes available in network"
            })
            return

        # Find the next smallest ID larger than current master
        current_nodes = sorted(list(self.known_nodes))

        new_master_id = None

        if self.master_id is None:
            # If no master exists, pick the smallest ID
            new_master_id = current_nodes[0]
        else:
            # Find the next smallest ID after the failed master
            for node_id in current_nodes:
                if node_id > self.master_id:
                    new_master_id = node_id
                    break

        if new_master_id is None:
            # If no node found after current master, wrap around to the smallest
            new_master_id = current_nodes[0]

        self.master_id = new_master_id

        # Notify GUI about transition period
        self.send_to_gui('MASTER_TRANSITION_START', {})

        # Wait for 1 second
        time.sleep(1)

        # Notify all nodes about new master
        message = {
            'type': 'NEW_MASTER',
            'from': self.handler_id,  # From handler
            'data': {'master_id': new_master_id}
        }

        # Broadcast to all known nodes using node IDs
        self.broadcast_to_nodes(message)

        # Update GUI about completion of transition and new master
        self.send_to_gui('MASTER_TRANSITION_END', {})
        self.send_to_gui('MASTER_CHANGED', {
            'master_id': new_master_id
        })
        self.send_to_gui('LOG', {
            'message': f"Node {new_master_id} assigned as new master"
        })

        logging.info(f"Assigned Node {new_master_id} as new master")

    def check_node_status(self):
        """Monitor all nodes' heartbeat status"""
        current_time = time.time()
        nodes_to_remove = set()

        # Check all known nodes
        for node_id in self.known_nodes:
            if (node_id not in self.last_heartbeat or
                current_time - self.last_heartbeat[node_id] > self.heartbeat_timeout):
                logging.info(f"Node {node_id} heartbeat timeout detected")
                nodes_to_remove.add(node_id)

                # Send log message to GUI
                self.send_to_gui('LOG', {
                    'message': f"Node {node_id} lost - heartbeat timeout"
                })

        # Remove lost nodes and notify GUI
        for node_id in nodes_to_remove:
            self.known_nodes.remove(node_id)
            self.send_to_gui('NODE_REMOVED', {
                'node_id': node_id
            })

            # If master node was removed, assign new master
            if node_id == self.master_id:
                logging.info("Master node lost - assigning new master")
                self.assign_new_master()

    def send_to_gui(self, message_type, data):
        """Send message to GUI using V2X communication"""
        message = {
             'type': message_type,
             'from': self.handler_id,
             'data': data
         }
        try:
            json_message = json.dumps(message, cls=JSONEncoder)
            drone_v2x.send(json_message, (self.gui_group, self.gui_id))
        except Exception as e:
            logging.error(f"Error sending to GUI: {e}")

    def send_network_state(self):
        """Send current network state to GUI"""
        time.sleep(0.5)  # Short delay to ensure GUI is ready

        # Send all known nodes
        for node_id in self.known_nodes:
            self.send_to_gui('NODE_ADDED', {
                'node_id': node_id,
                'node_type': 'NODE'
            })

        # Send handler as a special node
        self.send_to_gui('NODE_ADDED', {
            'node_id': self.handler_id,
            'node_type': 'HANDLER'
        })

        # Send current master status
        if self.master_id is not None:
            self.send_to_gui('MASTER_CHANGED', {
                'master_id': self.master_id
            })

        logging.info(f"Sent network state: nodes={self.known_nodes}, master={self.master_id}, handler={self.handler_id}")

    def calculate_node_score(self, node_id):
        """Calculate node score based on multiple factors"""
        current_time = time.time()
        score = 0.0

        # Factor 1: Early Join Time (40% weight)
        if node_id in self.join_timestamps:
            join_time = self.join_timestamps[node_id]
            time_score = 1.0 - (join_time - min(self.join_timestamps.values())) / 30.0  # Normalize to 30 sec window
            time_score = max(0, min(1, time_score))  # Clamp between 0 and 1
            score += 0.4 * time_score

        # Factor 2: Heartbeat Reliability (40% weight)
        if node_id in self.heartbeat_consistency:
            # Calculate standard deviation of heartbeat intervals
            intervals = self.heartbeat_consistency[node_id]
            if intervals:
                std_dev = statistics.stdev(intervals) if len(intervals) > 1 else 0
                consistency_score = 1.0 - (min(std_dev, 1.0))  # Lower std_dev = better score
                score += 0.4 * consistency_score

        # Factor 3: Node ID preference (20% weight)
        id_score = 1.0 - (node_id / 20.0)  # Lower ID = better score, normalize to reasonable range
        score += 0.2 * id_score

        return score

    def update_heartbeat_consistency(self, node_id, timestamp):
        """Update heartbeat consistency tracking for a node"""
        if node_id not in self.heartbeat_consistency:
            self.heartbeat_consistency[node_id] = []

        # Calculate interval from last heartbeat
        if self.last_heartbeat.get(node_id):
            interval = timestamp - self.last_heartbeat[node_id]
            if len(self.heartbeat_consistency[node_id]) >= self.heartbeat_window_size:
                self.heartbeat_consistency[node_id].pop(0)
            self.heartbeat_consistency[node_id].append(interval)

    def select_initial_master(self):
        """Smart master selection during initialization phase"""
        # Calculate scores for all nodes
        scores = {}
        for node_id in self.known_nodes:
            scores[node_id] = self.calculate_node_score(node_id)

        # Select node with highest score
        if scores:
            new_master_id = max(scores.items(), key=lambda x: x[1])[0]
            logging.info(f"Initial master selection scores: {scores}")
            logging.info(f"Selected Node {new_master_id} as initial master")
            return new_master_id
        return None

    def check_initialization_complete(self):
        """Check if initialization phase is complete"""
        if self.initialization_phase and len(self.known_nodes) >= self.expected_nodes:
            logging.info("All expected nodes have joined - completing initialization")

            # Select initial master
            new_master_id = self.select_initial_master()
            if new_master_id:
                self.master_id = new_master_id
                # Notify all nodes about selected master
                message = {
                    'type': 'NEW_MASTER',
                    'from': self.handler_id,
                    'data': {'master_id': new_master_id}
                }
                self.broadcast_to_nodes(message)

                # Notify GUI
                self.send_to_gui('INITIALIZATION_COMPLETE', {
                    'master_id': new_master_id
                })
                self.send_to_gui('MASTER_CHANGED', {
                    'master_id': new_master_id
                })

            self.initialization_phase = False

    def broadcast_to_nodes(self, message):
        """Broadcast message to all known nodes using V2X communication"""
        for node_id in self.known_nodes:
            try:
                # Format message as JSON
                json_message = json.dumps(message, cls=JSONEncoder)
                # Send message to node with group 11, id node_id
                drone_v2x.send(json_message, (self.node_group, node_id))
                logging.debug(f"Broadcast message to node {node_id} (Group {self.node_group})")
            except Exception as e:
                logging.error(f"Error broadcasting to node {node_id}: {e}")

    def send_drone_command(self, node_id, command, params=None):
        """Send drone command to specific node using V2X communication"""
        # Check if this is a command for the handler's own drone
        if node_id == self.handler_id:
            result = self._handle_handler_drone_command(command, params)
            
            # Send result to GUI
            self.send_to_gui('DRONE_COMMAND_RESULT', {
                'node_id': self.handler_id,
                'command': command,
                'result': result,
                'timestamp': time.time()
            })
            
            success = result.get('success', False)
            message_text = result.get('message', '')
            log_level = logging.INFO if success else logging.WARNING
            logging.log(log_level, f"Handler {self.handler_id} command '{command}' result: {message_text}")

            self.send_to_gui('LOG', {
                'message': f"Handler {self.handler_id} - {command}: {message_text}",
                'level': 'success' if success else 'error'
            })
            
            return success

        # Command for other nodes
        if node_id not in self.known_nodes:
            logging.error(f"Cannot send command to unknown node {node_id}")
            return False

        message = {
            'type': 'DRONE_COMMAND',
            'from': self.handler_id,  # From handler
            'data': {
                'command': command,
                'params': params or {}
            }
        }

        try:
            # Format message as JSON
            json_message = json.dumps(message, cls=JSONEncoder)
            # Send message to node with group 11, id node_id
            drone_v2x.send(json_message, (self.node_group, node_id))

            logging.info(f"Sent drone command '{command}' to Node {node_id} (Group {self.node_group})")
            return True

        except Exception as e:
            logging.error(f"Error sending drone command to node {node_id}: {e}")
            return False

    def get_node_status(self, node_id=None):
        """Get status for a specific node or all nodes

        Args:
            node_id: Optional node ID to get status for.
                If None, returns status for all nodes.

        Returns:
            dict: Status information for the requested node(s)
        """
        if not hasattr(self, 'node_statuses'):
            return {}

        if node_id is not None:
            # Return status for specific node
            return self.node_statuses.get(node_id, {}).get('status', {})
        else:
            # Return all node statuses
            result = {}
            for nid, data in self.node_statuses.items():
                result[nid] = data.get('status', {})
            return result

    def process_node_message(self, message, addr):
        """Process incoming messages from nodes with initialization phase handling and drone command support"""
        msg_type = message['type']
        from_node = message['from']
        data = message.get('data', {})

        current_time = time.time()

        # Update heartbeat tracking (exclude handler's own messages)
        if from_node != self.handler_id:
            self.last_heartbeat[from_node] = current_time
            self.update_heartbeat_consistency(from_node, current_time)

        # Handle different message types during initialization phase
        if self.initialization_phase:
            if from_node not in self.known_nodes and from_node != self.handler_id:
                # New node joining during initialization
                self.known_nodes.add(from_node)
                self.join_timestamps[from_node] = current_time

                logging.info(f"Initialization phase: Node {from_node} joined (Total: {len(self.known_nodes)}/{self.expected_nodes})")

                # Notify GUI about new node
                self.send_to_gui('NODE_ADDED', {
                    'node_id': from_node,
                    'node_type': 'NODE'
                })

                self.send_to_gui('LOG', {
                    'message': f"Initialization: Node {from_node} joined. Waiting for {self.expected_nodes - len(self.known_nodes)} more nodes..."
                })

                # Check if all nodes have joined
                self.check_initialization_complete()

            # During initialization, only process heartbeats, node registration, and command acks
            if msg_type not in ['NODE_HEARTBEAT', 'NODE_ADDED', 'COMMAND_ACK']:
                return

        # Process messages after initialization phase or command acks during initialization

        # Process drone command acknowledgments (both during and after initialization)
        if msg_type == 'COMMAND_ACK':
            # Process drone command acknowledgment
            command = data.get('command')
            result = data.get('result', {})

            # Store the command response
            self.command_responses[command] = result

            # Forward command result to GUI
            self.send_to_gui('DRONE_COMMAND_RESULT', {
                'node_id': from_node,
                'command': command,
                'result': result,
                'timestamp': data.get('timestamp', current_time)
            })

            # Log command result
            success = result.get('success', False)
            message_text = result.get('message', '')
            log_level = logging.INFO if success else logging.WARNING
            logging.log(log_level, f"Node {from_node} command '{command}' result: {message_text}")

            # Send log message to GUI
            self.send_to_gui('LOG', {
                'message': f"Node {from_node} - {command}: {message_text}",
                'level': 'success' if success else 'error'
            })

            return  # Command ack handled, return early

        # If still in initialization phase, don't process other messages yet
        if self.initialization_phase:
            return

        # Handle new node registration after initialization
        if from_node not in self.known_nodes and from_node != self.handler_id:
            self.known_nodes.add(from_node)
            self.join_timestamps[from_node] = current_time

            logging.info(f"New node joined after initialization: Node {from_node}")

            # Send node addition to GUI
            self.send_to_gui('NODE_ADDED', {
                'node_id': from_node,
                'node_type': 'NODE'
            })

            self.send_to_gui('LOG', {
                'message': f"Node {from_node} joined network"
            })

        # Handle different message types
        if msg_type == 'NODE_SHUTDOWN':
            if from_node in self.known_nodes:
                self.known_nodes.remove(from_node)
                if from_node in self.join_timestamps:
                    del self.join_timestamps[from_node]
                if from_node in self.heartbeat_consistency:
                    del self.heartbeat_consistency[from_node]

                self.send_to_gui('NODE_REMOVED', {
                    'node_id': from_node
                })

                self.send_to_gui('LOG', {
                    'message': f"Node {from_node} has left the network"
                })

                # If master node was removed, assign new master
                if from_node == self.master_id:
                    logging.info("Master node removed - assigning new master")
                    self.assign_new_master()

        elif msg_type == 'MASTER_HEARTBEAT':
            if from_node == self.master_id:
                # Confirm master status to GUI
                self.send_to_gui('MASTER_HEARTBEAT', {
                    'master_id': from_node,
                    'timestamp': current_time
                })

                # If drone status included in heartbeat, forward to GUI
                if 'armed' in data or 'mode' in data or 'altitude' in data:
                    self.send_to_gui('MASTER_DRONE_STATUS', {
                        'master_id': from_node,
                        'drone_status': {
                            'armed': data.get('armed', False),
                            'mode': data.get('mode'),
                            'altitude': data.get('altitude', 0),
                            'timestamp': current_time
                        }
                    })

        elif msg_type == 'NODE_HEARTBEAT':
            # Process regular node heartbeat
            # If drone status included in heartbeat, forward to GUI
            if 'armed' in data or 'mode' in data or 'altitude' in data:
                self.send_to_gui('NODE_DRONE_STATUS', {
                    'node_id': from_node,
                    'drone_status': {
                        'armed': data.get('armed', False),
                        'mode': data.get('mode'),
                        'altitude': data.get('altitude', 0),
                        'timestamp': current_time
                    }
                })

        elif msg_type == 'MASTER_HEALTH_UPDATE':
            # Optional: Process any health metrics from master node
            if from_node == self.master_id:
                health_data = data.get('health_metrics', {})
                self.send_to_gui('MASTER_HEALTH', {
                    'master_id': from_node,
                    'health_data': health_data
                })

        elif msg_type == 'DRONE_ERROR':
            # Handle drone error reports from nodes
            error_message = data.get('error', 'Unknown error')
            error_code = data.get('code', 0)

            logging.error(f"Drone error from Node {from_node}: {error_message} (Code: {error_code})")

            # Forward to GUI
            self.send_to_gui('DRONE_ERROR', {
                'node_id': from_node,
                'error': error_message,
                'code': error_code,
                'timestamp': current_time
            })

            # Send log message to GUI
            self.send_to_gui('LOG', {
                'message': f"Drone error from Node {from_node}: {error_message}",
                'level': 'error'
            })

        elif msg_type == 'DRONE_STATUS_UPDATE':
            # Process detailed drone status update from a node
            status_data = data.get('status', {})
            timestamp = data.get('timestamp', current_time)

            # Store status info for internal use
            if not hasattr(self, 'node_statuses'):
                self.node_statuses = {}

            # Update node status
            self.node_statuses[from_node] = {
                'timestamp': timestamp,
                'status': status_data
            }

            # Forward to GUI with properly formatted data for display
            gui_status_data = {
                'node_id': from_node,
                'is_master': (from_node == self.master_id),
                'armed': status_data.get('armed', False),
                'flight_mode': status_data.get('mode', 'UNKNOWN'),
                'altitude': status_data.get('altitude', 0),
                'position': status_data.get('position', None),
                'heading': status_data.get('heading', None),
                'groundspeed': status_data.get('groundspeed', None),
                'gps': status_data.get('gps', None),
                'battery': status_data.get('battery', None),
                'system_status': status_data.get('system_status', None),
                'timestamp': timestamp
            }

            self.send_to_gui('DRONE_STATUS_UPDATE', gui_status_data)

            # Only log significant changes for console clarity
            significant_change = False
            if from_node not in getattr(self, 'last_logged_status', {}):
                self.last_logged_status = getattr(self, 'last_logged_status', {})
                self.last_logged_status[from_node] = {
                    'armed': None,
                    'mode': None,
                    'altitude': None,
                    'timestamp': 0
                }
                significant_change = True

            # Check if important status has changed or if it's been a while since last log
            last_log = self.last_logged_status[from_node]
            if (status_data.get('armed') != last_log['armed'] or
                    status_data.get('mode') != last_log['mode'] or
                    abs(status_data.get('altitude', 0) - (last_log['altitude'] or 0)) > 5 or
                    timestamp - last_log['timestamp'] > 10):  # Log at least every 10 seconds
                significant_change = True

            if significant_change:
                # Update last logged status
                self.last_logged_status[from_node] = {
                    'armed': status_data.get('armed'),
                    'mode': status_data.get('mode'),
                    'altitude': status_data.get('altitude'),
                    'timestamp': timestamp
                }

                # Log the status update
                armed_status = "ARMED" if status_data.get('armed') else "DISARMED"
                mode = status_data.get('mode', 'UNKNOWN')
                alt = status_data.get('altitude', 0)
                pos_str = "Unknown"
                if status_data.get('position'):
                    lat, lon = status_data.get('position')
                    pos_str = f"({lat:.6f}, {lon:.6f})"

                log_message = f"Node {from_node} status: {armed_status}, Mode: {mode}, Alt: {alt:.1f}m, Pos: {pos_str}"

                # Send log message to GUI only for significant changes
                self.send_to_gui('LOG', {
                    'message': log_message,
                    'level': 'info'
                })

    def process_gui_message(self, message, addr):
        """Process incoming messages from the GUI"""
        msg_type = message.get('type')
        data = message.get('data', {})

        if msg_type == 'GUI_CONNECTED':
            logging.info("GUI connected - sending network state")
            self.send_network_state()
            return

        if msg_type != 'GUI_COMMAND':
            logging.warning(f"Received unknown message type from GUI: {msg_type}")
            return

        command_type = data.get('command_type')
        target_node = data.get('target_node')

        logging.info(f"Received GUI command: {command_type}, target: {target_node}")

        # Process different command types
        if command_type == 'ARM_DRONE':
            if target_node == 'all':
                # Send arm command to all nodes including handler
                for node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'arm')
                # Also arm handler's drone if connected
                if self.drone_connected:
                    self.send_drone_command(self.handler_id, 'arm')

                self.send_to_gui('LOG', {
                    'message': "Sending ARM command to all nodes and handler"
                })
            else:
                # Send arm command to specific node
                node_id = int(target_node)
                if node_id == self.handler_id or node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'arm')

                    entity_type = "handler" if node_id == self.handler_id else "node"
                    self.send_to_gui('LOG', {
                        'message': f"Sending ARM command to {entity_type} {node_id}"
                    })
                else:
                    self.send_to_gui('LOG', {
                        'message': f"Error: Node {node_id} not found",
                        'level': 'error'
                    })

        elif command_type == 'DISARM_DRONE':
            if target_node == 'all':
                # Send disarm command to all nodes including handler
                for node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'disarm')
                # Also disarm handler's drone if connected
                if self.drone_connected:
                    self.send_drone_command(self.handler_id, 'disarm')

                self.send_to_gui('LOG', {
                    'message': "Sending DISARM command to all nodes and handler"
                })
            else:
                # Send disarm command to specific node
                node_id = int(target_node)
                if node_id == self.handler_id or node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'disarm')

                    entity_type = "handler" if node_id == self.handler_id else "node"
                    self.send_to_gui('LOG', {
                        'message': f"Sending DISARM command to {entity_type} {node_id}"
                    })
                else:
                    self.send_to_gui('LOG', {
                        'message': f"Error: Node {node_id} not found",
                        'level': 'error'
                    })

        elif command_type == 'SET_FLIGHT_MODE':
            mode = data.get('mode')
            if not mode:
                self.send_to_gui('LOG', {
                    'message': "Error: No flight mode specified",
                    'level': 'error'
                })
                return

            if target_node == 'all':
                # Send mode command to all nodes including handler
                for node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'set_mode', {'mode': mode})
                # Also set handler's drone mode if connected
                if self.drone_connected:
                    self.send_drone_command(self.handler_id, 'set_mode', {'mode': mode})

                self.send_to_gui('LOG', {
                    'message': f"Setting all nodes and handler to {mode} mode"
                })
            else:
                # Send mode command to specific node
                node_id = int(target_node)
                if node_id == self.handler_id or node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'set_mode', {'mode': mode})

                    entity_type = "handler" if node_id == self.handler_id else "node"
                    self.send_to_gui('LOG', {
                        'message': f"Setting {entity_type} {node_id} to {mode} mode"
                    })
                else:
                    self.send_to_gui('LOG', {
                        'message': f"Error: Node {node_id} not found",
                        'level': 'error'
                    })

        elif command_type == 'TAKEOFF':
            # Default altitude if not specified
            altitude = data.get('altitude', 6.0)

            if target_node == 'all':
                # Send takeoff command to all nodes including handler
                for node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'takeoff', {'altitude': altitude})
                # Also takeoff handler's drone if connected
                if self.drone_connected:
                    self.send_drone_command(self.handler_id, 'takeoff', {'altitude': altitude})

                self.send_to_gui('LOG', {
                    'message': f"Commanding all nodes and handler to takeoff to altitude {altitude}m"
                })
            else:
                # Send takeoff command to specific node
                node_id = int(target_node)
                if node_id == self.handler_id or node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'takeoff', {'altitude': altitude})

                    entity_type = "handler" if node_id == self.handler_id else "node"
                    self.send_to_gui('LOG', {
                        'message': f"Commanding {entity_type} {node_id} to takeoff to altitude {altitude}m"
                    })
                else:
                    self.send_to_gui('LOG', {
                        'message': f"Error: Node {node_id} not found",
                        'level': 'error'
                    })

        elif command_type == 'EMERGENCY_STOP':
            if target_node == 'all':
                # Send emergency stop to all nodes including handler
                # First set all to BRAKE mode
                for node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'set_mode', {'mode': 'BRAKE'})
                # Also brake handler's drone if connected
                if self.drone_connected:
                    self.send_drone_command(self.handler_id, 'set_mode', {'mode': 'BRAKE'})

                self.send_to_gui('LOG', {
                    'message': "EMERGENCY STOP issued for all nodes and handler - setting to BRAKE mode",
                    'level': 'warning'
                })

                # Then attempt to disarm all after a short delay
                time.sleep(1.0)
                for node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'disarm')
                # Also disarm handler's drone if connected
                if self.drone_connected:
                    self.send_drone_command(self.handler_id, 'disarm')

                self.send_to_gui('LOG', {
                    'message': "Attempting to disarm all nodes and handler",
                    'level': 'warning'
                })
            else:
                # Send emergency stop to specific node
                node_id = int(target_node)
                if node_id == self.handler_id or node_id in self.known_nodes:
                    # First set to BRAKE mode
                    self.send_drone_command(node_id, 'set_mode', {'mode': 'BRAKE'})

                    entity_type = "handler" if node_id == self.handler_id else "node"
                    self.send_to_gui('LOG', {
                        'message': f"EMERGENCY STOP issued for {entity_type} {node_id} - setting to BRAKE mode",
                        'level': 'warning'
                    })

                    # Then attempt to disarm after a short delay
                    time.sleep(1.0)
                    self.send_drone_command(node_id, 'disarm')

                    self.send_to_gui('LOG', {
                        'message': f"Attempting to disarm {entity_type} {node_id}",
                        'level': 'warning'
                    })
                else:
                    self.send_to_gui('LOG', {
                        'message': f"Error: Node {node_id} not found",
                        'level': 'error'
                    })

        elif command_type == 'FORCE_MASTER_ELECTION':
            # Force a new master election
            logging.info("GUI requested forced master election")

            self.send_to_gui('LOG', {
                'message': "Initiating forced master election"
            })

            self.assign_new_master()

        elif command_type == 'REFRESH_MAP':
            # Refresh the network state to update the GUI map
            logging.info("GUI requested network map refresh")
            self.send_network_state()

            self.send_to_gui('LOG', {
                'message': "Network map refreshed"
            })
        
        elif command_type == 'FLY_TO_HERE':
            # Get parameters
            distance = data.get('distance', 5.0)  # Default to 5m
            angle = data.get('angle', 0.0)        # Default to forward (0 degrees)

            if target_node == 'all':
                # Send fly command to all nodes including handler
                for node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'fly_to_here', {'distance': distance, 'angle': angle})
                # Also command handler's drone if connected
                if self.drone_connected:
                    self.send_drone_command(self.handler_id, 'fly_to_here', {'distance': distance, 'angle': angle})

                self.send_to_gui('LOG', {
                    'message': f"Commanding all nodes and handler to fly {distance}m at {angle}° angle"
                })
            else:
                # Send fly command to specific node
                node_id = int(target_node)
                if node_id == self.handler_id or node_id in self.known_nodes:
                    self.send_drone_command(node_id, 'fly_to_here', {'distance': distance, 'angle': angle})

                    entity_type = "handler" if node_id == self.handler_id else "node"
                    self.send_to_gui('LOG', {
                        'message': f"Commanding {entity_type} {node_id} to fly {distance}m at {angle}° angle"
                    })
                else:
                    self.send_to_gui('LOG', {
                        'message': f"Error: Node {node_id} not found",
                        'level': 'error'
                    })

        else:
            logging.warning(f"Unknown GUI command type: {command_type}")
            self.send_to_gui('LOG', {
                'message': f"Unknown command: {command_type}",
                'level': 'error'
            })

    def run(self):
        self.is_running = True

        while self.is_running:
            try:
                # Check for messages from nodes using V2X communication
                try:
                    data, addr = drone_v2x.recv(1400)
                    message = json.loads(data.decode().rstrip('\x00'))
                    # Process the message based on sender
                    from_id = message.get('from', 0)
                    
                    # Check if message is from GUI
                    if from_id == self.gui_id:
                        self.process_gui_message(message, addr)
                    else:
                        # Message from node
                        self.process_node_message(message, addr)
                        
                except Exception as e:
                    # No message or error
                    if str(e) != "timed out": # Ignore timeout errors
                        logging.error(f"Error processing V2X message: {e}")

                time.sleep(0.01)  # Short sleep to prevent CPU overuse

            except Exception as e:
                logging.error(f"Error in main handler loop: {e}")
                time.sleep(0.1)  # Prevent rapid error loops

    def _monitor_network(self):
        """Thread to monitor all nodes status"""
        while self.is_running:
            self.check_node_status()
            time.sleep(1)

    def start(self):
        # Start main processing thread
        threading.Thread(target=self.run, daemon=True).start()

        # Start network monitoring thread
        threading.Thread(target=self._monitor_network, daemon=True).start()

        # Start auto-connect process for handler's drone
        threading.Thread(target=self._auto_connect, daemon=True).start()

        logging.info("Network handler started")

    def stop(self):
        self.is_running = False
        
        # Stop handler's drone connection
        if self.drone_connected:
            self._stop_status_reporting()
            self.drone_controller.cleanup()
            
        # Make sure terminal is reset when stopping
        reset_terminal()
        logging.info("Network handler stopped")


def main():
    handler_id = 11  # Default handler ID (changed from 10 to 11)
    gui_group = 1    # Default GUI group
    gui_id = 1       # Default GUI ID
    
    # Check if handler ID is provided as command line argument
    if len(sys.argv) > 1:
        try:
            handler_id = int(sys.argv[1])
            if handler_id < 1 or handler_id > 255:
                print("Error: Handler ID must be between 1 and 255")
                sys.exit(1)
        except ValueError:
            print("Error: Invalid handler ID format, must be an integer")
            sys.exit(1)
    
    # Check if GUI group and ID are provided as command line arguments
    if len(sys.argv) > 3:
        try:
            gui_group = int(sys.argv[2])
            gui_id = int(sys.argv[3])
            if gui_group < 1 or gui_group > 255 or gui_id < 1 or gui_id > 255:
                print("Error: GUI group and ID must be between 1 and 255")
                sys.exit(1)
        except ValueError:
            print("Error: Invalid GUI group/ID format, must be integers")
            sys.exit(1)
    
    logging.info("Starting network handler...")
    try:
        handler = NetworkHandler(handler_id=handler_id, gui_group=gui_group, gui_id=gui_id)
        handler.start()

        print("\nHandler running with V2X communication:")
        print(f"Handler Group: {handler.group}, Handler ID: {handler.handler_id}")
        print(f"Connecting to nodes in Group: {handler.node_group}, IDs: 13-14")
        print(f"GUI communication: Group {handler.gui_group}, ID {handler.gui_id}")
        print("Handler drone connection: udp:127.0.0.1:14550")
        print("\nHandler is running in background mode.")
        print("- Handler will automatically try to connect to its drone")
        print("- Use the GUI to control drones and monitor the network")
        print("- Handler can be controlled like any other drone through the GUI")
        print("Press Ctrl+C to stop the handler.\n")

        # Keep the main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        if 'handler' in locals():
            handler.stop()
        print("\nHandler stopped")
    except Exception as e:
        logging.error(f"Error running handler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()