import statistics
import sys
import socket
import json
import time
import threading
import logging
import cmd
import atexit
import os

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

class NetworkHandler:
    def __init__(self, mesh_ip='192.168.199.0', outside_ip='0.0.0.0'):
        # Mesh network interface (for nodes)
        self.mesh_host = mesh_ip
        self.mesh_port = 5000
        
        # Outside network interface (for GUI)
        self.outside_host = outside_ip
        self.outside_port = 5566  # Port for receiving GUI messages
        self.gui_host = '192.168.1.2'  # GUI's outside IP
        self.gui_port = 5567  # GUI's port
        
        self.is_running = False
        self.known_nodes = set()
        self.master_id = None  # Initialize with no master
        self.last_network_change = time.time()
        
        # Node health tracking
        self.last_heartbeat = {}
        self.heartbeat_timeout = 6  # Seconds before considering a node dead
        
        # Initialization phase attributes
        self.initialization_phase = True
        self.expected_nodes = 9
        self.node_scores = {}
        self.join_timestamps = {}
        self.heartbeat_consistency = {}
        self.heartbeat_window_size = 10
        
        # Command response tracking
        self.command_responses = {}
        
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
            logging.info("No eligible node found for new master")
            self.send_to_gui('LOG', {
                'message': "No eligible node found for new master"    
            })
            return
            
        self.master_id = new_master_id
        
        # Notify GUI about transition period
        self.send_to_gui('MASTER_TRANSITION_START', {})
        
        # Wait for 1 seconds
        time.sleep(1)

        # Notify all nodes about new master
        message = {
            'type': 'NEW_MASTER',
            'from': 0,  # From handler
            'data': {'master_id': new_master_id}
        }

        # Broadcast to all known nodes using IP addresses
        base_ip = '.'.join(self.mesh_host.split('.')[:-1])
        for node_id in self.known_nodes:
            try:
                node_ip = f"{base_ip}.{node_id}"
                self.node_socket.sendto(
                    json.dumps(message).encode(),
                    (node_ip, self.mesh_port)
                )
            except Exception as e:
                logging.error(f"Error sending new master message to node {node_id}: {e}")

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
                'ip_last_byte': node_id,
                'node_type': 'NODE'
            })
        
        # Send current master status
        if self.master_id is not None:
            self.send_to_gui('MASTER_CHANGED', {
                'master_id': self.master_id
            })
            
        logging.info(f"Sent network state: nodes={self.known_nodes}, master={self.master_id}")

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
        id_score = 1.0 - (node_id / self.expected_nodes)  # Lower ID = better score
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
                    'from': 0,
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
        """Broadcast message to all known nodes"""
        base_ip = '.'.join(self.mesh_host.split('.')[:-1])
        for node_id in self.known_nodes:
            try:
                node_ip = f"{base_ip}.{node_id}"
                self.node_socket.sendto(
                    json.dumps(message).encode(),
                    (node_ip, self.mesh_port)
                )
            except Exception as e:
                logging.error(f"Error broadcasting to node {node_id}: {e}")

    def send_drone_command(self, node_id, command, params=None):
        """Send drone command to specific node"""
        if node_id not in self.known_nodes:
            logging.error(f"Cannot send command to unknown node {node_id}")
            return False

        message = {
            'type': 'DRONE_COMMAND',
            'from': 0,  # From handler
            'data': {
                'command': command,
                'params': params or {}
            }
        }

        try:
            # Construct node IP from base network
            base_ip = '.'.join(self.mesh_host.split('.')[:-1])
            node_ip = f"{base_ip}.{node_id}"
            
            self.node_socket.sendto(
                json.dumps(message).encode(),
                (node_ip, self.mesh_port)
            )
            
            logging.info(f"Sent drone command '{command}' to Node {node_id}")
            return True
            
        except Exception as e:
            logging.error(f"Error sending drone command to node {node_id}: {e}")
            return False

    def process_node_message(self, message, addr):
        """Process incoming messages from nodes with initialization phase handling and drone command support"""
        msg_type = message['type']
        from_node = message['from']
        data = message.get('data', {})
        
        current_time = time.time()
        
        # Update heartbeat tracking
        self.last_heartbeat[from_node] = current_time
        self.update_heartbeat_consistency(from_node, current_time)
        
        # Handle different message types during initialization phase
        if self.initialization_phase:
            if from_node not in self.known_nodes:
                # New node joining during initialization
                self.known_nodes.add(from_node)
                self.join_timestamps[from_node] = current_time
                
                logging.info(f"Initialization phase: Node {from_node} joined (Total: {len(self.known_nodes)}/{self.expected_nodes})")
                
                # Notify GUI about new node
                self.send_to_gui('NODE_ADDED', {
                    'ip_last_byte': from_node,
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
        if from_node not in self.known_nodes:
            self.known_nodes.add(from_node)
            self.join_timestamps[from_node] = current_time
            
            logging.info(f"New node joined after initialization: Node {from_node}")
            
            # Send node addition to GUI
            self.send_to_gui('NODE_ADDED', {
                'ip_last_byte': from_node,
                'node_type': 'NODE'
            })
            
            self.send_to_gui('LOG', {
                'message': f"Node {from_node} (Port {5000 + from_node}) joined network"
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

    def run(self):
        self.is_running = True
        
        while self.is_running:
            try:
                # Check for node messages
                data, addr = self.node_socket.recvfrom(1024)
                message = json.loads(data.decode())
                
                if message['type'] == 'GUI_CONNECTED':
                    logging.info("GUI connected - sending network state")
                    self.send_network_state()
                else:
                    self.process_node_message(message, addr)
                    
            except socket.timeout:
                continue
            except Exception as e:
                logging.error(f"Error processing message: {e}")
            
            time.sleep(0.1)  # Prevent CPU overuse

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

        logging.info("Network handler started")

    def stop(self):
        self.is_running = False
        try:
            self.node_socket.close()
            self.gui_socket.close()
        except Exception:
            pass
        # Make sure terminal is reset when stopping
        reset_terminal()
        logging.info("Network handler stopped")


class HandlerShell(cmd.Cmd):
    intro = 'Welcome to the Network Handler Shell. Type help or ? to list commands.\n'
    prompt = '(handler) '

    def __init__(self, handler):
        super().__init__()
        self.handler = handler
        self.last_command_node = None

    def do_nodes(self, arg):
        """
        List all connected nodes in the network
        """
        if not self.handler.known_nodes:
            print("No nodes connected to the network")
            return
            
        print("\nConnected Nodes:")
        print("-" * 40)
        print(f"{'Node ID':<10}{'Master':<10}{'Last Heartbeat':<20}")
        print("-" * 40)
        
        for node_id in sorted(self.handler.known_nodes):
            is_master = "Yes" if node_id == self.handler.master_id else "No"
            last_hb = time.time() - self.handler.last_heartbeat.get(node_id, 0)
            last_hb_str = f"{last_hb:.1f}s ago"
            
            print(f"{node_id:<10}{is_master:<10}{last_hb_str:<20}")
        print()

    def do_select(self, arg):
        """
        Select a node to send commands to
        Usage: select <node_id>
        """
        try:
            node_id = int(arg)
            if node_id in self.handler.known_nodes:
                self.last_command_node = node_id
                print(f"Selected Node {node_id} for commands")
            else:
                print(f"Error: Node {node_id} is not connected")
        except ValueError:
            print("Error: Please provide a valid node ID")

    def _broadcast_command(self, command, params=None):
        """
        Broadcast command to all known nodes
        Returns: True if command was sent to at least one node
        """
        if not self.handler.known_nodes:
            print("Error: No nodes connected to broadcast command to")
            return False
            
        print(f"Broadcasting '{command}' command to all {len(self.handler.known_nodes)} nodes...")
        success_count = 0
        
        for node_id in sorted(self.handler.known_nodes):
            if self.handler.send_drone_command(node_id, command, params):
                success_count += 1
                print(f"- Command sent to Node {node_id}")
        
        if success_count > 0:
            print(f"Command '{command}' broadcast to {success_count} nodes")
            return True
        else:
            print("Failed to broadcast command to any nodes")
            return False

    def do_connect(self, arg):
        """
        Connect to drone
        Usage: connect [node_id|all]
        If node_id is not provided, uses the last selected node
        Use 'connect all' to connect all drones in the network
        """
        if arg.lower() == 'all':
            self._broadcast_command('connect')
        else:
            node_id = self._get_target_node(arg)
            if node_id:
                if self.handler.send_drone_command(node_id, 'connect'):
                    print(f"Connect command sent to Node {node_id}")
                    
                    # Wait for response
                    self._wait_for_command_response('connect')

    def do_arm(self, arg):
        """
        Arm the drone
        Usage: arm [node_id|all]
        If node_id is not provided, uses the last selected node
        Use 'arm all' to arm all drones in the network
        """
        if arg.lower() == 'all':
            self._broadcast_command('arm')
        else:
            node_id = self._get_target_node(arg)
            if node_id:
                if self.handler.send_drone_command(node_id, 'arm'):
                    print(f"Arm command sent to Node {node_id}")
                    
                    # Wait for response
                    self._wait_for_command_response('arm')

    def do_disarm(self, arg):
        """
        Disarm the drone
        Usage: disarm [node_id|all]
        If node_id is not provided, uses the last selected node
        Use 'disarm all' to disarm all drones in the network
        """
        if arg.lower() == 'all':
            self._broadcast_command('disarm')
        else:
            node_id = self._get_target_node(arg)
            if node_id:
                if self.handler.send_drone_command(node_id, 'disarm'):
                    print(f"Disarm command sent to Node {node_id}")
                    
                    # Wait for response
                    self._wait_for_command_response('disarm')

    def do_mode(self, arg):
        """
        Set flight mode
        Usage: mode <mode_name> [node_id|all]
        Example: mode GUIDED 3
        Example: mode GUIDED all
        If node_id is not provided, uses the last selected node
        """
        args = arg.split()
        if not args:
            print("Error: Please specify a flight mode")
            return
            
        mode_name = args[0]
        target = args[1] if len(args) > 1 else None
        
        if target and target.lower() == 'all':
            self._broadcast_command('set_mode', {'mode': mode_name})
        else:
            node_id = self._get_target_node(target)
            if node_id:
                if self.handler.send_drone_command(node_id, 'set_mode', {'mode': mode_name}):
                    print(f"Set mode '{mode_name}' command sent to Node {node_id}")
                    
                    # Wait for response
                    self._wait_for_command_response('set_mode')

    def do_getmode(self, arg):
        """
        Get current flight mode
        Usage: getmode [node_id|all]
        If node_id is not provided, uses the last selected node
        Use 'getmode all' to get mode from all drones
        """
        if arg.lower() == 'all':
            self._broadcast_command('get_mode')
        else:
            node_id = self._get_target_node(arg)
            if node_id:
                if self.handler.send_drone_command(node_id, 'get_mode'):
                    print(f"Get mode command sent to Node {node_id}")
                    
                    # Wait for response
                    self._wait_for_command_response('get_mode')

    def do_takeoff(self, arg):
        """
        Take off to specified altitude
        Usage: takeoff <altitude> [node_id|all]
        Example: takeoff 10 2
        Example: takeoff a10 all
        If node_id is not provided, uses the last selected node
        """
        args = arg.split()
        if not args:
            print("Error: Please specify an altitude")
            return
            
        try:
            altitude = float(args[0])
            target = args[1] if len(args) > 1 else None
            
            if target and target.lower() == 'all':
                self._broadcast_command('takeoff', {'altitude': altitude})
            else:
                node_id = self._get_target_node(target)
                if node_id:
                    if self.handler.send_drone_command(node_id, 'takeoff', {'altitude': altitude}):
                        print(f"Takeoff command sent to Node {node_id} - target altitude: {altitude}m")
                        
                        # Wait for response
                        self._wait_for_command_response('takeoff')
                    
        except ValueError:
            print("Error: Please provide a valid altitude in meters")

    def do_throttle(self, arg):
        """
        Set throttle value
        Usage: throttle <value> [node_id|all]
        Example: throttle 50 1
        Example: throttle 50 all
        If node_id is not provided, uses the last selected node
        """
        args = arg.split()
        if not args:
            print("Error: Please specify a throttle value (0-100)")
            return
            
        try:
            value = int(args[0])
            if value < 0 or value > 100:
                print("Error: Throttle value must be between 0 and 100")
                return
                
            target = args[1] if len(args) > 1 else None
            
            if target and target.lower() == 'all':
                self._broadcast_command('set_throttle', {'value': value})
            else:
                node_id = self._get_target_node(target)
                if node_id:
                    if self.handler.send_drone_command(node_id, 'set_throttle', {'value': value}):
                        print(f"Set throttle command sent to Node {node_id} - value: {value}%")
                        
                        # Wait for response
                        self._wait_for_command_response('set_throttle')
                    
        except ValueError:
            print("Error: Please provide a valid throttle value (0-100)")

    def do_status(self, arg):
        """
        Get drone status
        Usage: status [node_id|all]
        If node_id is not provided, uses the last selected node
        Use 'status all' to get status from all drones
        """
        if arg.lower() == 'all':
            self._broadcast_command('get_status')
        else:
            node_id = self._get_target_node(arg)
            if node_id:
                if self.handler.send_drone_command(node_id, 'get_status'):
                    print(f"Status request sent to Node {node_id}")
                    
                    # Wait for response
                    self._wait_for_command_response('get_status')

    def do_stop(self, arg):
        """
        Execute emergency stop on drones
        Usage: stop [node_id|all]
        If node_id is not provided, uses the last selected node
        Use 'stop all' to emergency stop all drones in the network
        
        Emergency stop forces drones to BRAKE mode and disarms them if possible
        """
        if arg.lower() == 'all' or not arg:
            # Default to all nodes if no argument provided for safety
            print("Broadcasting emergency stop to ALL NODES...")
            
            # First set all nodes to BRAKE mode
            brake_success = self._broadcast_command('set_mode', {'mode': 'BRAKE'})
            
            if brake_success:
                print("BRAKE mode command broadcast complete")
                
                print("Emergency stop sequence completed")
                print("Note: Some drones may not be able to disarm while in flight")
                print("      Check status of all nodes with 'status all'")
            else:
                print("Failed to broadcast emergency stop commands to any nodes")
        else:
            # Target specific node
            node_id = self._get_target_node(arg)
            if node_id:
                print(f"Executing emergency stop on Node {node_id}...")
                
                # First set node to BRAKE mode
                if self.handler.send_drone_command(node_id, 'set_mode', {'mode': 'BRAKE'}):
                    print(f"BRAKE mode command sent to Node {node_id}")
                    self._wait_for_command_response('set_mode')

                    print(f"Emergency stop sequence completed for Node {node_id}")
                else:
                    print(f"Failed to send emergency stop commands to Node {node_id}")
        

    def _get_target_node(self, arg):
        """Helper to get target node for commands"""
        if arg:
            try:
                node_id = int(arg)
                if node_id in self.handler.known_nodes:
                    return node_id
                else:
                    print(f"Error: Node {node_id} is not connected")
                    return None
            except ValueError:
                print("Error: Please provide a valid node ID")
                return None
        elif self.last_command_node:
            if self.last_command_node in self.handler.known_nodes:
                return self.last_command_node
            else:
                print(f"Error: Previously selected Node {self.last_command_node} is no longer connected")
                self.last_command_node = None
                return None
        else:
            print("Error: No node selected. Use 'select <node_id>' or specify node ID with command")
            return None
            
    def _wait_for_command_response(self, command, timeout=5):
        """Wait for command response with timeout"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if command in self.handler.command_responses:
                result = self.handler.command_responses[command]
                # Clear the response to prevent re-use
                del self.handler.command_responses[command]
                
                success = result.get('success', False)
                message = result.get('message', '')
                
                if success:
                    print(f"Command successful: {message}")
                else:
                    print(f"Command failed: {message}")
                
                # If this is a status response, print detailed information
                if command == 'get_status' and 'status' in result:
                    status = result['status']
                    print("\nDrone Status:")
                    print("-" * 40)
                    for key, value in status.items():
                        print(f"{key}: {value}")
                    print("-" * 40)
                
                return True
            time.sleep(0.1)
            
        print(f"Timeout waiting for response to {command} command")
        return False
    
def main():
    logging.info("Starting network handler...")
    try:
        handler = NetworkHandler()
        handler.start()

        print("\nHandler running on two interfaces:")
        print(f"Mesh network: {handler.mesh_host}:{handler.mesh_port}")
        print(f"Outside network: {handler.outside_host}:{handler.outside_port}")
        print(f"Sending GUI updates to {handler.gui_host}:{handler.gui_port}")
        print("\nStarting interactive shell. Type 'help' for commands.")
        
        # Start interactive shell
        shell = HandlerShell(handler)
        
        # Run the shell in a separate thread so the handler can continue running
        shell_thread = threading.Thread(target=shell.cmdloop)
        shell_thread.daemon = True
        shell_thread.start()
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
            if not shell_thread.is_alive():
                break
                
    except KeyboardInterrupt:
        if 'handler' in locals():
            handler.stop()
        print("\nHandler stopped")
    except Exception as e:
        logging.error(f"Error running handler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()