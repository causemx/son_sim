import sys
import time
import json
import threading
import logging
import argparse
from enum import Enum
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass
from libs.controller import DroneController, FlightMode
from libs import drone_v2x

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class NodeRole(Enum):
    FOLLOWER = "follower"
    LEADER = "leader"
    CANDIDATE = "candidate"

class NodeState(Enum):
    INITIALIZING = "initializing"
    RUNNING = "running"
    ELECTION = "election"
    ROLE_SWITCHING = "role_switching"
    STOPPING = "stopping"
    STOPPED = "stopped"

@dataclass
class NetworkConfig:
    """Network configuration for the failover system"""
    node_id: int
    leader_group: int = 1        # Leaders are always in group 1
    follower_group: int = 11     # Followers are always in group 11
    gui_group: int = 1
    gui_id: int = 1
    expected_nodes: Set[int] = None
    leader_timeout: float = 5.0
    election_timeout: float = 3.0
    heartbeat_interval: float = 1.0

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

class DroneCommandHandler:
    """Handles drone commands using the existing controller.py"""
    
    def __init__(self, node_id: int, connection_string: str):
        self.node_id = node_id
        self.logger = logging.getLogger(f"{__name__}.DroneCommands-{node_id}")
        
        # Initialize drone controller (from your existing controller.py)
        self.drone_controller = DroneController(connection_string)
        self.drone_connected = False
        
        # Status tracking
        self.last_command_time = 0
        self.command_count = 0
        
    def connect_drone(self, max_retries: int = 5, retry_delay: float = 2.0) -> bool:
        """Connect to drone with retry logic"""
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Drone connection attempt {attempt + 1}/{max_retries}")
                
                if self.drone_controller.connect(baudrate=57600):
                    self.drone_connected = True
                    self.logger.info("Successfully connected to drone")
                    return True
                else:
                    self.logger.warning(f"Connection attempt {attempt + 1} failed")
                    
            except Exception as e:
                self.logger.error(f"Connection error on attempt {attempt + 1}: {e}")
                
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                
        self.logger.error("Failed to connect to drone after all attempts")
        return False
        
    def disconnect_drone(self) -> Dict[str, Any]:
        """Disconnect from drone"""
        try:
            if self.drone_connected:
                self.drone_controller.cleanup()
                self.drone_connected = False
                return {'success': True, 'message': 'Disconnected successfully'}
            else:
                return {'success': True, 'message': 'Already disconnected'}
        except Exception as e:
            return {'success': False, 'message': f'Disconnect error: {str(e)}'}
            
    def execute_command(self, command: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute drone command using controller.py methods"""
        
        if not params:
            params = {}
            
        self.command_count += 1
        self.last_command_time = time.time()
        
        self.logger.info(f"Executing command: {command} with params: {params}")
        
        try:
            # Handle connection command
            if command == 'connect':
                if not self.drone_connected:
                    success = self.connect_drone()
                    return {
                        'success': success, 
                        'message': 'Connected successfully' if success else 'Connection failed'
                    }
                else:
                    return {'success': True, 'message': 'Already connected'}
                    
            # Check if drone is connected for other commands
            if not self.drone_connected:
                return {'success': False, 'message': 'Drone not connected. Use connect command first.'}
                
            # ARM command
            if command == 'arm':
                success = self.drone_controller.arm()
                return {
                    'success': success,
                    'message': 'Drone armed successfully' if success else 'Failed to arm drone'
                }
                
            # DISARM command  
            elif command == 'disarm':
                success = self.drone_controller.disarm()
                return {
                    'success': success,
                    'message': 'Drone disarmed successfully' if success else 'Failed to disarm drone'
                }
                
            # TAKEOFF command
            elif command == 'takeoff':
                if 'altitude' not in params:
                    return {'success': False, 'message': 'Altitude parameter required for takeoff'}
                    
                try:
                    altitude = float(params['altitude'])
                    if altitude <= 0 or altitude > 100:  # Safety limits
                        return {'success': False, 'message': 'Altitude must be between 0 and 100 meters'}
                        
                    success = self.drone_controller.takeoff(altitude)
                    return {
                        'success': success,
                        'message': f'Takeoff command sent - target altitude: {altitude}m' if success else 'Takeoff command failed'
                    }
                except ValueError:
                    return {'success': False, 'message': 'Invalid altitude value'}
                    
            # LAND command
            elif command == 'land':
                success = self.drone_controller.land()
                return {
                    'success': success,
                    'message': 'Landing command sent' if success else 'Land command failed'
                }
                
            # SET_MODE command
            elif command == 'set_mode':
                if 'mode' not in params:
                    return {'success': False, 'message': 'Mode parameter required'}
                    
                mode_str = params['mode'].upper()
                
                # Validate flight mode using your FlightMode enum
                try:
                    flight_mode = FlightMode.from_string(mode_str)
                    if not flight_mode:
                        available_modes = [m.value for m in FlightMode]
                        return {
                            'success': False, 
                            'message': f'Invalid flight mode: {mode_str}. Available: {available_modes}'
                        }
                        
                    success = self.drone_controller.set_flight_mode(flight_mode)
                    return {
                        'success': success,
                        'message': f'Flight mode set to {mode_str}' if success else f'Failed to set mode to {mode_str}'
                    }
                except Exception as e:
                    return {'success': False, 'message': f'Flight mode error: {str(e)}'}
                    
            # GET_MODE command
            elif command == 'get_mode':
                try:
                    current_mode = self.drone_controller.get_current_mode()
                    if current_mode:
                        # Handle both enum and string returns
                        if hasattr(current_mode, 'value'):
                            mode_value = current_mode.value
                        else:
                            mode_value = str(current_mode)
                            
                        return {
                            'success': True,
                            'message': f'Current flight mode: {mode_value}',
                            'mode': mode_value
                        }
                    else:
                        return {'success': False, 'message': 'Could not retrieve flight mode'}
                except Exception as e:
                    return {'success': False, 'message': f'Get mode error: {str(e)}'}
                    
            # SET_THROTTLE command
            elif command == 'set_throttle':
                if 'value' not in params:
                    return {'success': False, 'message': 'Throttle value parameter required'}
                    
                try:
                    throttle_value = int(params['value'])
                    if throttle_value < 0 or throttle_value > 100:
                        return {'success': False, 'message': 'Throttle value must be between 0 and 100'}
                        
                    success = self.drone_controller.set_throttle(throttle_value)
                    return {
                        'success': success,
                        'message': f'Throttle set to {throttle_value}%' if success else 'Failed to set throttle'
                    }
                except ValueError:
                    return {'success': False, 'message': 'Invalid throttle value - must be integer'}
                    
            # GET_STATUS command
            elif command == 'get_status':
                try:
                    status = self.drone_controller.get_drone_status()
                    return {
                        'success': True,
                        'message': 'Status retrieved successfully',
                        'status': status
                    }
                except Exception as e:
                    return {'success': False, 'message': f'Status error: {str(e)}'}
                    
            # FLY_TO_HERE command (using your controller's fly_to_here method)
            elif command == 'fly_to_here':
                if 'distance' not in params or 'angle' not in params:
                    return {'success': False, 'message': 'Distance and angle parameters required'}
                    
                try:
                    distance = float(params['distance'])
                    angle = float(params['angle'])
                    
                    # Safety limits
                    if distance <= 0 or distance > 50:  # Max 50m
                        return {'success': False, 'message': 'Distance must be between 0 and 50 meters'}
                        
                    if angle < -180 or angle > 180:
                        return {'success': False, 'message': 'Angle must be between -180 and 180 degrees'}
                        
                    success = self.drone_controller.fly_to_here(distance, angle)
                    return {
                        'success': success,
                        'message': f'Fly command sent - distance: {distance}m, angle: {angle}°' if success else 'Fly command failed'
                    }
                except ValueError:
                    return {'success': False, 'message': 'Invalid distance or angle values'}
                except Exception as e:
                    return {'success': False, 'message': f'Fly command error: {str(e)}'}
                    
            # DISCONNECT command
            elif command == 'disconnect':
                return self.disconnect_drone()
                
            # Unknown command
            else:
                available_commands = [
                    'connect', 'arm', 'disarm', 'takeoff', 'land', 
                    'set_mode', 'get_mode', 'set_throttle', 'get_status', 
                    'fly_to_here', 'disconnect'
                ]
                return {
                    'success': False, 
                    'message': f'Unknown command: {command}. Available: {available_commands}'
                }
                
        except Exception as e:
            self.logger.error(f"Error executing command {command}: {e}", exc_info=True)
            return {'success': False, 'message': f'Command execution error: {str(e)}'}
            
    def get_drone_status(self) -> Dict[str, Any]:
        """Get current drone status from controller"""
        if not self.drone_connected:
            return {
                'connected': False,
                'node_id': self.node_id
            }
            
        try:
            # Get status from your existing controller
            status = self.drone_controller.get_drone_status()
            
            # Add node-specific information
            status.update({
                'node_id': self.node_id,
                'command_count': self.command_count,
                'last_command_time': self.last_command_time,
                'connected': self.drone_connected
            })
            
            return status
            
        except Exception as e:
            self.logger.error(f"Error getting drone status: {e}")
            return {
                'connected': False,
                'node_id': self.node_id,
                'error': str(e)
            }

class LeaderElection:
    """Implements Bully Algorithm for leader election"""
    
    def __init__(self, node_id: int, known_nodes: Set[int]):
        self.node_id = node_id
        self.known_nodes = known_nodes
        self.logger = logging.getLogger(f"{__name__}.Election")
        self.election_in_progress = False
        self.election_responses = set()
        self.election_timeout = 3.0
        
    def start_election(self) -> bool:
        """Start leader election using Bully Algorithm"""
        if self.election_in_progress:
            return False
            
        self.logger.info(f"Node {self.node_id} starting leader election")
        self.election_in_progress = True
        self.election_responses.clear()
        
        # Send ELECTION message to all higher-numbered nodes
        higher_nodes = {n for n in self.known_nodes if n > self.node_id}
        
        if not higher_nodes:
            # No higher nodes, we become leader
            self.logger.info(f"Node {self.node_id} elected as leader (highest ID)")
            self.election_in_progress = False
            return True
            
        # Send election messages to higher nodes
        for node_id in higher_nodes:
            self._send_election_message(node_id)
            
        # Wait for responses
        start_time = time.time()
        while (time.time() - start_time < self.election_timeout and 
               len(self.election_responses) == 0):
            time.sleep(0.1)
            
        self.election_in_progress = False
        
        if not self.election_responses:
            # No responses from higher nodes, we become leader
            self.logger.info(f"Node {self.node_id} elected as leader (no higher node responses)")
            return True
        else:
            # Higher node responded, they will handle election
            self.logger.info(f"Node {self.node_id} stepping back from election")
            return False
            
    def handle_election_message(self, from_node: int) -> bool:
        """Handle incoming election message"""
        if from_node < self.node_id:
            # We have higher ID, respond and start our own election
            self._send_election_response(from_node)
            return self.start_election()
        return False
        
    def _send_election_message(self, target_node: int):
        """Send election message to target node"""
        message = {
            'type': 'ELECTION',
            'from': self.node_id,
            'data': {'election_id': int(time.time() * 1000)}
        }
        try:
            json_message = json.dumps(message, cls=JSONEncoder)
            # Send to follower group (since all nodes in election are followers)
            drone_v2x.send(json_message, (11, target_node))
            self.logger.debug(f"Sending ELECTION to node {target_node} in group 11")
        except Exception as e:
            self.logger.error(f"Failed to send election message to {target_node}: {e}")
        
    def _send_election_response(self, target_node: int):
        """Send election response to target node"""
        message = {
            'type': 'ELECTION_RESPONSE',
            'from': self.node_id,
            'data': {}
        }
        try:
            json_message = json.dumps(message, cls=JSONEncoder)
            # Send to follower group (since all nodes in election are followers)
            drone_v2x.send(json_message, (11, target_node))
            self.logger.debug(f"Sending ELECTION_RESPONSE to node {target_node} in group 11")
        except Exception as e:
            self.logger.error(f"Failed to send election response to {target_node}: {e}")

class UnifiedNode:
    """Unified node that can operate as both follower and leader with integrated drone control"""
    
    def __init__(self, node_id: int, initial_leader_id: Optional[int] = None):
        self.node_id = node_id
        self.config = NetworkConfig(
            node_id=node_id,
            expected_nodes={11, 12}  # Adjust based on your setup
        )
        
        # Remove self from expected nodes
        if node_id in self.config.expected_nodes:
            self.config.expected_nodes.remove(node_id)
            
        self.logger = logging.getLogger(f"{__name__}.UnifiedNode-{node_id}")
        self.state = NodeState.INITIALIZING
        
        # Initialize drone command handler with proper controller integration
        connection_string = "/dev/ttyAMA0"
        self.drone_handler = DroneCommandHandler(node_id, connection_string)
        
        # Core components
        self.election = LeaderElection(node_id, self.config.expected_nodes)
        
        # Network state
        self.known_nodes = set()
        self.current_leader = initial_leader_id
        self.is_running = False
        self.current_role = NodeRole.FOLLOWER
        self.current_group = self.config.follower_group  # Start in follower group
        
        # Leader-specific attributes
        self.leader_components = None
        self.follower_components = None
        
        # Initialize V2X communication
        try:
            drone_v2x.init()
            self.logger.info(f"V2X communication initialized in group {self.current_group}")
        except Exception as e:
            self.logger.error(f"Failed to initialize V2X: {e}")
            raise
            
    def start(self, as_leader: bool = False):
        """Start the unified node"""
        self.is_running = True
        self.state = NodeState.RUNNING
        
        # Set initial group based on role
        if as_leader:
            self._switch_to_leader_group()
        else:
            self._switch_to_follower_group()
        
        # Connect to drone
        threading.Thread(target=self._connect_to_drone, daemon=True).start()
        
        # Start in appropriate role
        if as_leader:
            self._become_leader()
        else:
            self._become_follower()
            
        # Start main message loop
        threading.Thread(target=self._main_message_loop, daemon=True).start()
        
        # Start failure detection
        threading.Thread(target=self._failure_detector, daemon=True).start()
        
        # Start status reporting
        threading.Thread(target=self._status_reporter, daemon=True).start()
        
        self.logger.info(f"Unified node {self.node_id} started as {self.current_role.value} in group {self.current_group}")
        
    def _switch_to_leader_group(self):
        """Switch to leader group (group 1)"""
        try:
            if self.current_group != self.config.leader_group:
                drone_v2x.set_group(self.config.leader_group)
                self.current_group = self.config.leader_group
                self.logger.info(f"Switched to leader group {self.config.leader_group}")
        except Exception as e:
            self.logger.error(f"Failed to switch to leader group: {e}")
            
    def _switch_to_follower_group(self):
        """Switch to follower group (group 11)"""
        try:
            if self.current_group != self.config.follower_group:
                drone_v2x.set_group(self.config.follower_group)
                self.current_group = self.config.follower_group
                self.logger.info(f"Switched to follower group {self.config.follower_group}")
        except Exception as e:
            self.logger.error(f"Failed to switch to follower group: {e}")
            
    def _connect_to_drone(self):
        """Connect to drone with retry logic"""
        if self.drone_handler.connect_drone():
            self.logger.info("Successfully connected to drone")
            
            # If we successfully connected, send NODE_ADDED to leader
            if self.current_role == NodeRole.FOLLOWER and self.current_leader:
                self._send_to_leader('NODE_ADDED', {'node_id': self.node_id})
        else:
            self.logger.error("Failed to connect to drone")
            
    def _status_reporter(self):
        """Thread function to continuously report drone status"""
        while self.is_running:
            try:
                if self.drone_handler.drone_connected:
                    # Get status from drone handler
                    status = self.drone_handler.get_drone_status()
                    
                    # Send to appropriate destination based on role
                    if self.current_role == NodeRole.FOLLOWER and self.current_leader:
                        # Send to leader
                        self._send_to_leader('DRONE_STATUS_UPDATE', {
                            'status': status,
                            'timestamp': time.time()
                        })
                    elif self.current_role == NodeRole.LEADER:
                        # Send to GUI
                        self._send_to_gui('DRONE_STATUS_UPDATE', {
                            'node_id': self.node_id,
                            'is_master': True,
                            'is_handler': True,
                            **status,
                            'timestamp': time.time()
                        })
                        
                time.sleep(0.5)  # Report every 0.5 seconds
            except Exception as e:
                self.logger.error(f"Error in status reporter: {e}")
                time.sleep(1)
                
    def _main_message_loop(self):
        """Main message processing loop"""
        while self.is_running:
            try:
                # Receive messages via V2X
                data, addr = drone_v2x.recv(1400)
                message = json.loads(data.decode().rstrip('\x00'))
                self._process_message(message)
                
            except Exception as e:
                if "timed out" not in str(e):
                    self.logger.error(f"Error in message loop: {e}")
                time.sleep(0.01)
                
    def _process_message(self, message: Dict[str, Any]):
        """Process incoming messages based on current role"""
        msg_type = message.get('type')
        from_node = message.get('from')
        data = message.get('data', {})
        
        if msg_type == 'ELECTION':
            self._handle_election_message(message)
        elif msg_type == 'ELECTION_RESPONSE':
            self.election.election_responses.add(from_node)
        elif msg_type == 'NEW_LEADER':
            self._handle_new_leader(message)
        elif msg_type == 'LEADER_HEARTBEAT':
            self._handle_leader_heartbeat(message)
        elif self.current_role == NodeRole.LEADER:
            self._process_leader_message(message)
        else:
            self._process_follower_message(message)
            
    def _handle_election_message(self, message: Dict[str, Any]):
        """Handle election message"""
        from_node = message['from']
        if self.election.handle_election_message(from_node):
            self._become_leader()
            
    def _handle_new_leader(self, message: Dict[str, Any]):
        """Handle new leader announcement"""
        new_leader_id = message['data']['leader_id']
        if new_leader_id != self.node_id:
            self.current_leader = new_leader_id
            if self.current_role == NodeRole.LEADER:
                self._become_follower()
                
    def _handle_leader_heartbeat(self, message: Dict[str, Any]):
        """Handle heartbeat from leader"""
        if self.current_role == NodeRole.FOLLOWER and self.follower_components:
            self.follower_components['last_leader_heartbeat'] = time.time()
                
    def _process_leader_message(self, message: Dict[str, Any]):
        """Process message when acting as leader"""
        msg_type = message.get('type')
        from_node = message.get('from')
        data = message.get('data', {})
        
        if msg_type == 'NODE_HEARTBEAT':
            self._handle_node_heartbeat(message)
        elif msg_type == 'NODE_ADDED':
            self._handle_node_added(message)
        elif msg_type == 'GUI_CONNECTED':
            self._handle_gui_connection(message)
        elif msg_type == 'GUI_COMMAND':
            self._handle_gui_command(message)
        elif msg_type == 'DRONE_STATUS_UPDATE':
            self._handle_drone_status_update(message)
        elif msg_type == 'COMMAND_ACK':
            self._handle_command_ack(message)
        
    def _process_follower_message(self, message: Dict[str, Any]):
        """Process message when acting as follower"""
        msg_type = message.get('type')
        
        if msg_type == 'DRONE_COMMAND':
            self._handle_drone_command(message)
        elif msg_type == 'NEW_MASTER':
            self._handle_master_assignment(message)
            
    def _failure_detector(self):
        """Detect leader failures and trigger elections"""
        while self.is_running:
            try:
                if (self.current_role == NodeRole.FOLLOWER and 
                    self.current_leader is not None):
                    
                    # Check if we've lost contact with leader
                    if self._is_leader_failed():
                        self.logger.warning("Leader failure detected, starting election")
                        if self.election.start_election():
                            self._become_leader()
                            
                time.sleep(1.0)
                
            except Exception as e:
                self.logger.error(f"Error in failure detector: {e}")
                time.sleep(1.0)
                
    def _is_leader_failed(self) -> bool:
        """Check if current leader has failed"""
        if not self.follower_components:
            return False
            
        last_heartbeat = self.follower_components.get('last_leader_heartbeat', 0)
        return time.time() - last_heartbeat > self.config.leader_timeout
        
    def _become_leader(self):
        """Transition to leader role"""
        self.logger.info(f"Node {self.node_id} becoming leader")
        self.state = NodeState.ROLE_SWITCHING
        
        # Switch to leader group FIRST
        self._switch_to_leader_group()
        
        # Stop follower components
        if self.follower_components:
            self.follower_components = None
            
        # Initialize leader components
        self.leader_components = {
            'known_nodes': set(),
            'last_heartbeat': {},
            'node_statuses': {},
            'gui_connected': False,
            'master_id': self.node_id
        }
        
        self.current_role = NodeRole.LEADER
        self.current_leader = self.node_id
        
        # Start leader-specific threads
        threading.Thread(target=self._leader_heartbeat_sender, daemon=True).start()
        threading.Thread(target=self._leader_network_monitor, daemon=True).start()
        
        self._announce_leadership()
        self.state = NodeState.RUNNING
        self.logger.info(f"Node {self.node_id} is now the leader in group {self.current_group}")
            
    def _become_follower(self):
        """Transition to follower role"""
        if self.current_leader:
            self.logger.info(f"Node {self.node_id} becoming follower (leader: {self.current_leader})")
            self.state = NodeState.ROLE_SWITCHING
            
            # Switch to follower group
            self._switch_to_follower_group()
            
            # Stop leader components
            if self.leader_components:
                self.leader_components = None
                
            # Initialize follower components
            self.follower_components = {
                'leader_id': self.current_leader,
                'last_leader_heartbeat': time.time(),
                'master_id': None
            }
            
            self.current_role = NodeRole.FOLLOWER
            
            self.state = NodeState.RUNNING
            self.logger.info(f"Node {self.node_id} is now a follower in group {self.current_group}")
                
    def _announce_leadership(self):
        """Announce leadership to all nodes"""
        message = {
            'type': 'NEW_LEADER',
            'from': self.node_id,
            'data': {'leader_id': self.node_id}
        }
        
        # Broadcast to all known nodes in follower group
        for target_node in self.config.expected_nodes:
            try:
                json_message = json.dumps(message, cls=JSONEncoder)
                drone_v2x.send(json_message, (self.config.follower_group, target_node))
                self.logger.debug(f"Announced leadership to node {target_node} in group {self.config.follower_group}")
            except Exception as e:
                self.logger.error(f"Failed to announce leadership to node {target_node}: {e}")
                
    def _leader_heartbeat_sender(self):
        """Send periodic heartbeats as leader"""
        while self.current_role == NodeRole.LEADER and self.is_running:
            try:
                # Send heartbeat to all known nodes in follower group
                for target_node in self.config.expected_nodes:
                    message = {
                        'type': 'LEADER_HEARTBEAT',
                        'from': self.node_id,
                        'data': {'timestamp': time.time()}
                    }
                    try:
                        json_message = json.dumps(message, cls=JSONEncoder)
                        drone_v2x.send(json_message, (self.config.follower_group, target_node))
                    except Exception as e:
                        self.logger.error(f"Failed to send heartbeat to {target_node}: {e}")
                        
                time.sleep(self.config.heartbeat_interval)
            except Exception as e:
                self.logger.error(f"Error in heartbeat sender: {e}")
                time.sleep(self.config.heartbeat_interval)
                
    def _leader_network_monitor(self):
        """Monitor network health as leader"""
        while self.current_role == NodeRole.LEADER and self.is_running:
            try:
                if self.leader_components:
                    current_time = time.time()
                    timeout_nodes = []
                    
                    for node_id, last_seen in self.leader_components['last_heartbeat'].items():
                        if current_time - last_seen > self.config.leader_timeout:
                            timeout_nodes.append(node_id)
                            
                    for node_id in timeout_nodes:
                        self.logger.warning(f"Node {node_id} timeout detected")
                        self._handle_node_failure(node_id)
                        
                time.sleep(1.0)
            except Exception as e:
                self.logger.error(f"Error in network monitor: {e}")
                time.sleep(1.0)
                
    def _handle_node_failure(self, failed_node_id: int):
        """Handle node failure detection"""
        if self.leader_components and failed_node_id in self.leader_components['known_nodes']:
            self.leader_components['known_nodes'].remove(failed_node_id)
            self.logger.info(f"Removed failed node {failed_node_id} from network")
            
            # Notify GUI
            self._send_to_gui('NODE_REMOVED', {'node_id': failed_node_id})
            
    def _handle_node_heartbeat(self, message: Dict[str, Any]):
        """Handle heartbeat from follower node (leader only)"""
        if self.leader_components:
            node_id = message['from']
            self.leader_components['last_heartbeat'][node_id] = time.time()
            self.leader_components['known_nodes'].add(node_id)
            
    def _handle_node_added(self, message: Dict[str, Any]):
        """Handle node addition (leader only)"""
        if self.leader_components:
            node_id = message['data']['node_id']
            self.leader_components['known_nodes'].add(node_id)
            self.leader_components['last_heartbeat'][node_id] = time.time()
            
            # Notify GUI
            self._send_to_gui('NODE_ADDED', {
                'node_id': node_id,
                'node_type': 'NODE'
            })
            
            self.logger.info(f"Node {node_id} added to network")
            
    def _handle_gui_connection(self, message: Dict[str, Any]):
        """Handle GUI connection (leader only)"""
        if self.leader_components:
            self.leader_components['gui_connected'] = True
            self.logger.info("GUI connected to leader")
            
            # Send current network state to GUI
            self._send_network_state_to_gui()
            
    def _send_network_state_to_gui(self):
        """Send current network state to GUI"""
        if not self.leader_components:
            return
            
        # Send all known nodes
        for node_id in self.leader_components['known_nodes']:
            self._send_to_gui('NODE_ADDED', {
                'node_id': node_id,
                'node_type': 'NODE'
            })
            
        # Send handler as a special node
        self._send_to_gui('NODE_ADDED', {
            'node_id': self.node_id,
            'node_type': 'HANDLER'
        })
        
        # Send current master status
        self._send_to_gui('MASTER_CHANGED', {
            'master_id': self.leader_components['master_id']
        })
        
    def _handle_gui_command(self, message: Dict[str, Any]):
        """Handle GUI command (leader only)"""
        data = message.get('data', {})
        command_type = data.get('command_type')
        target_node = data.get('target_node')
        
        self.logger.info(f"Processing GUI command: {command_type}, target: {target_node}")
        
        # Handle commands for the leader's own drone
        if target_node == self.node_id or target_node == 'all':
            self._execute_local_drone_command(command_type, data)
            
        # Forward commands to other nodes
        if target_node == 'all':
            for node_id in self.leader_components.get('known_nodes', set()):
                self._send_drone_command_to_node(node_id, command_type, data)
        elif target_node != self.node_id and target_node in self.leader_components.get('known_nodes', set()):
            self._send_drone_command_to_node(target_node, command_type, data)
            
    def _execute_local_drone_command(self, command_type: str, data: Dict[str, Any]):
        """Execute drone command on leader's own drone"""
        try:
            # Map GUI command types to drone handler commands
            command_map = {
                'ARM_DRONE': 'arm',
                'DISARM_DRONE': 'disarm',
                'SET_FLIGHT_MODE': 'set_mode',
                'TAKEOFF': 'takeoff',
                'EMERGENCY_STOP': 'set_mode',  # Set to BRAKE mode
                'FLY_TO_HERE': 'fly_to_here'
            }
            
            drone_command = command_map.get(command_type)
            if not drone_command:
                self.logger.warning(f"Unknown command type: {command_type}")
                return
                
            # Prepare parameters
            params = {}
            if command_type == 'SET_FLIGHT_MODE':
                params['mode'] = data.get('mode', 'GUIDED')
            elif command_type == 'TAKEOFF':
                params['altitude'] = data.get('altitude', 6.0)
            elif command_type == 'EMERGENCY_STOP':
                params['mode'] = 'BRAKE'
            elif command_type == 'FLY_TO_HERE':
                params['distance'] = data.get('distance', 5.0)
                params['angle'] = data.get('angle', 0.0)
                
            # Execute command
            result = self.drone_handler.execute_command(drone_command, params)
            
            # Send result to GUI
            self._send_to_gui('DRONE_COMMAND_RESULT', {
                'node_id': self.node_id,
                'command': command_type,
                'result': result,
                'timestamp': time.time()
            })
            
            # Log result
            success = result.get('success', False)
            message_text = result.get('message', '')
            self._send_to_gui('LOG', {
                'message': f"Leader {self.node_id} - {command_type}: {message_text}",
                'level': 'success' if success else 'error'
            })
            
        except Exception as e:
            self.logger.error(f"Error executing local drone command: {e}")
            
    def _send_drone_command_to_node(self, node_id: int, command_type: str, data: Dict[str, Any]):
        """Send drone command to specific node - FIXED GROUP BUG"""
        # Map GUI commands to node commands
        command_map = {
            'ARM_DRONE': 'arm',
            'DISARM_DRONE': 'disarm',
            'SET_FLIGHT_MODE': 'set_mode',
            'TAKEOFF': 'takeoff',
            'EMERGENCY_STOP': 'set_mode',
            'FLY_TO_HERE': 'fly_to_here'
        }
        
        drone_command = command_map.get(command_type)
        if not drone_command:
            return
            
        # Prepare parameters
        params = {}
        if command_type == 'SET_FLIGHT_MODE':
            params['mode'] = data.get('mode', 'GUIDED')
        elif command_type == 'TAKEOFF':
            params['altitude'] = data.get('altitude', 6.0)
        elif command_type == 'EMERGENCY_STOP':
            params['mode'] = 'BRAKE'
        elif command_type == 'FLY_TO_HERE':
            params['distance'] = data.get('distance', 5.0)
            params['angle'] = data.get('angle', 0.0)
            
        message = {
            'type': 'DRONE_COMMAND',
            'from': self.node_id,
            'data': {
                'command': drone_command,
                'params': params
            }
        }
        
        try:
            json_message = json.dumps(message, cls=JSONEncoder)
            # FIXED: Use follower_group instead of non-existent self.config.group
            drone_v2x.send(json_message, (self.config.follower_group, node_id))
            self.logger.info(f"Sent drone command '{drone_command}' to Node {node_id} in group {self.config.follower_group}")
        except Exception as e:
            self.logger.error(f"Error sending drone command to node {node_id}: {e}")
            
    def _handle_drone_status_update(self, message: Dict[str, Any]):
        """Handle drone status update from nodes (leader only)"""
        if self.leader_components:
            node_id = message['from']
            status_data = message['data']['status']
            
            # Store status
            self.leader_components['node_statuses'][node_id] = status_data
            
            # Forward to GUI
            gui_status_data = {
                'node_id': node_id,
                'is_master': (node_id == self.leader_components.get('master_id')),
                **status_data,
                'timestamp': time.time()
            }
            
            self._send_to_gui('DRONE_STATUS_UPDATE', gui_status_data)
            
    def _handle_command_ack(self, message: Dict[str, Any]):
        """Handle command acknowledgment from nodes (leader only)"""
        node_id = message['from']
        command = message['data']['command']
        result = message['data']['result']
        
        # Forward to GUI
        self._send_to_gui('DRONE_COMMAND_RESULT', {
            'node_id': node_id,
            'command': command,
            'result': result,
            'timestamp': time.time()
        })
        
        # Log result
        success = result.get('success', False)
        message_text = result.get('message', '')
        self._send_to_gui('LOG', {
            'message': f"Node {node_id} - {command}: {message_text}",
            'level': 'success' if success else 'error'
        })
        
    def _handle_drone_command(self, message: Dict[str, Any]):
        """Handle drone command from leader (follower only)"""
        command = message['data'].get('command')
        params = message['data'].get('params', {})
        
        # Execute drone command
        result = self.drone_handler.execute_command(command, params)
        
        # Send acknowledgment back to leader in leader group
        ack_message = {
            'type': 'COMMAND_ACK',
            'from': self.node_id,
            'data': {
                'command': command,
                'result': result,
                'timestamp': time.time()
            }
        }
        
        try:
            json_message = json.dumps(ack_message, cls=JSONEncoder)
            # Send to leader group
            drone_v2x.send(json_message, (self.config.leader_group, self.current_leader))
        except Exception as e:
            self.logger.error(f"Failed to send command ACK: {e}")
            
    def _handle_master_assignment(self, message: Dict[str, Any]):
        """Handle master node assignment"""
        master_id = message['data']['master_id']
        if self.follower_components:
            self.follower_components['master_id'] = master_id
            
    def _send_to_leader(self, message_type: str, data: Dict[str, Any]):
        """Send message to current leader"""
        if self.current_leader:
            message = {
                'type': message_type,
                'from': self.node_id,
                'data': data
            }
            try:
                json_message = json.dumps(message, cls=JSONEncoder)
                # Send to leader group
                drone_v2x.send(json_message, (self.config.leader_group, self.current_leader))
            except Exception as e:
                self.logger.error(f"Error sending to leader: {e}")
                
    def _send_to_gui(self, message_type: str, data: Dict[str, Any]):
        """Send message to GUI (when leader)"""
        message = {
            'type': message_type,
            'from': self.node_id,
            'data': data
        }
        try:
            json_message = json.dumps(message, cls=JSONEncoder)
            drone_v2x.send(json_message, (self.config.gui_group, self.config.gui_id))
        except Exception as e:
            self.logger.error(f"Error sending to GUI: {e}")
            
    def stop(self):
        """Stop the unified node"""
        self.logger.info("Stopping unified node")
        self.is_running = False
        self.state = NodeState.STOPPING
        
        # Cleanup drone connection
        if self.drone_handler.drone_connected:
            self.drone_handler.disconnect_drone()
            
        self.state = NodeState.STOPPED
        self.logger.info("Unified node stopped")

def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("At least one argument must provided.")
        print("By running the script with the --help or -h flag, the argparse module will generate a help message.")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--leader", help="setup the leader's id")
    parser.add_argument("-f", "--follower", help="setup the follower's id")
    args = parser.parse_args()

    try:
        node_id = args.follower
        initial_leader_id = args.leader
        
        # Determine if this node should start as leader
        start_as_leader = (initial_leader_id is None or initial_leader_id == node_id)
        
        node = UnifiedNode(node_id, initial_leader_id)
        node.start(as_leader=start_as_leader)
        
        print(f"\nUnified Node {node_id} started:")
        print(f"Role: {'Leader' if start_as_leader else 'Follower'}")
        print(f"Group: {node.current_group}")
        if initial_leader_id and not start_as_leader:
            print(f"Initial Leader: {initial_leader_id}")
        print("\nNode supports dynamic role switching for fault tolerance")
        print("Integrated with your existing controller.py for drone commands")
        print("Press Ctrl+C to stop\n")
        
        try:
            while node.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            node.stop()
            
    except ValueError:
        print("Error: Node ID must be an integer")
        sys.exit(1)
    except Exception as e:
        print(f"Error starting node: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()