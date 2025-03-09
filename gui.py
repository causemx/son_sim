from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QDockWidget
)
from PyQt5.QtCore import pyqtSignal, QThread, Qt, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView
import folium
import io
import socket
import json
import sys
import time
import logging

# Configure logging to only show console output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class NetworkVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 300)
        self.nodes = {}
        self.last_heartbeat = {}
        self.last_positions = {}
        self.in_transition = False

        # Create a layout for the widget
        layout = QVBoxLayout()

        # Create a WebEngineView to display the Folium map
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view)

        self.setLayout(layout)

        # Create initial Folium map
        self._create_map()
        self.drone_statuses = {}


    def _create_map(self):
        """Create an initial empty map without grid lines"""
        # Center the map on the midpoint of our coordinate space (3, 3)
        self.map = folium.Map(
            location=[24.7736084, 121.0415506],
            zoom_start=14,
            tiles='CartoDB positron'  # Light map style
        )

        self.icons = ["glyphicon-cloud", "glyphicon-star", "glyphicon-home", "glyphicon-tree-conifer",
         "glyphicon-tree-deciduous", "glyphicon-fire", "glyphicon-flash", "glyphicon-road",
         "glyphicon-cutlery", "glyphicon-plane", "glyphicon-phone", "glyphicon-globe",
         "glyphicon-heart", "glyphicon-info-sign", "glyphicon-exclamation-sign",
         "glyphicon-thumbs-up", "glyphicon-thumbs-down", "glyphicon-fullscreen",
         "glyphicon-screenshot", "glyphicon-cloud-upload", "glyphicon-cloud-download"]

        # Add legend as a custom control
        legend_html = '''
             <div style="position: fixed;
                         bottom: 50px; right: 50px; width: 150px; height: 80px;
                         border:2px solid grey; z-index:9999; font-size:12px;
                         background-color: white;
                         padding: 10px">
                 <p><img src="https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png" width="15" height="15"> Master Node</p>
                 <p><img src="https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png" width="15" height="15"> Regular Node</p>
             </div>
             '''
        self.map.get_root().html.add_child(folium.Element(legend_html))

        # Display the map
        data = io.BytesIO()
        self.map.save(data, close_file=False)
        self.web_view.setHtml(data.getvalue().decode())

    def addNode(self, ip_last_byte, node_type):
        node_id = ip_last_byte
        if node_type == "MONITOR":
            return

        # Add node without position - position will be set by simulator
        self.nodes[node_id] = {
            "pos": None,  # Position will be updated by position simulator
            "type": node_type,
            "status": "Active",
            "color": 'blue',
            "ip_last_byte": ip_last_byte,
            "is_master": node_id == 1,
            "last_seen": time.time()
        }

        # If this is node 1, make it master
        if node_id == 1:
            self.updateMasterStatus(1)

        print(f"Node added: ID={node_id}, waiting for position from simulator")
        self._redraw()

    def removeNode(self, node_id):
        if node_id in self.nodes:
            if self.nodes[node_id]["pos"]:
                self.last_positions[node_id] = self.nodes[node_id]["pos"]
            del self.nodes[node_id]
            self._redraw()
    """
    def updateNodePosition(self, node_id, x, y):
        if node_id in self.nodes:
            # In Folium, we'll use [lat, lng] - but in our grid, we'll just use [y, x]
            self.nodes[node_id]["pos"] = (y, x)
            print(f"Node {node_id} position updated: ({x:.2f}, {y:.2f})")
            self._redraw()
        else:
            print(f"Position update for unknown node: {node_id}")
    """

    def updateMasterStatus(self, master_id):
        if self.in_transition:
            return

        # Reset all nodes to non-master first
        for node in self.nodes.values():
            node["is_master"] = False
            node["color"] = 'blue'

        # Set the new master if one is specified
        if master_id is not None and master_id in self.nodes:
            self.nodes[master_id]["is_master"] = True
            self.nodes[master_id]["color"] = 'red'
            print(f"Updated master status: Node {master_id} is now master")
        else:
            print("No master node currently assigned")

        self._redraw()

    def updateNodeStatus(self, node_id, status):
        if node_id in self.nodes:
            self.nodes[node_id]["status"] = status
            if self.nodes[node_id]["is_master"]:
                self.nodes[node_id]["color"] = 'red'
            else:
                self.nodes[node_id]["color"] = 'blue'
            self.nodes[node_id]["last_seen"] = time.time()

            print(f"Updated node {node_id} status: {status}")
            self._redraw()

    def startMasterTransition(self):
        self.in_transition = True
        print("Master transition started - pausing visualization updates")

    def endMasterTransition(self):
        self.in_transition = False
        print("Master transition ended - resuming visualization updates")
        self._redraw()

    def updateDroneStatus(self, node_id, status_data):
        """Update drone status information for a node"""
        if node_id in self.nodes:
            # Store the status data
            self.drone_statuses[node_id] = status_data
            
            # Check for position and handle [0.0, 0.0] case
            needs_position_simulation = False
            
            # Update position if provided in status
            if 'position' in status_data and status_data['position']:
                lat, lon = status_data['position']
                
                # Check if position is [0.0, 0.0] or very close to it
                if (abs(lat) < 0.0001 and abs(lon) < 0.0001):
                    # Position is effectively [0.0, 0.0], trigger simulation
                    needs_position_simulation = True
                    print(f"Node {node_id}: Received null position [0.0, 0.0], will simulate position")
                else:
                    # Valid position received, update node
                    # Only redraw if position changed significantly or not set
                    current_pos = self.nodes[node_id].get("pos")
                    if current_pos is None or abs(current_pos[0] - lat) > 0.0001 or abs(current_pos[1] - lon) > 0.0001:
                        self.nodes[node_id]["pos"] = (lat, lon)
                        print(f"Node {node_id}: Position updated to ({lat}, {lon})")
            else:
                # No position data in status update
                needs_position_simulation = self.nodes[node_id].get("pos") is None
            
            # Run position simulation if needed
            if needs_position_simulation:
                self._simulate_position_for_node(node_id)
            
            # Always update the node's status text
            status_text = "Active"
            if status_data.get('armed', False):
                status_text = f"ARMED [{status_data.get('flight_mode', 'UNKNOWN')}]"
            else:
                status_text = f"DISARMED [{status_data.get('flight_mode', 'UNKNOWN')}]"
            
            if self.nodes[node_id]["status"] != status_text:
                self.nodes[node_id]["status"] = status_text
            
            # Update last seen timestamp
            self.nodes[node_id]["last_seen"] = time.time()
            
            # Redraw map if needed
            self._redraw()

    def _simulate_position_for_node(self, node_id):
        """Simulate position for a single node"""
        if node_id not in self.nodes:
            return
        
        # Center coordinates (Taiwan coordinates)
        center_lat = 24.7739578
        center_lon = 121.0455114
        
        # Set up spacing for grid pattern (in degrees)
        lat_delta = 0.0002  # Approx. 22 meters between nodes
        lon_delta = 0.0003  # Approx. 33 meters between nodes
        
        # Calculate grid position based on node ID
        row = (node_id - 1) // 3    # 0, 0, 0, 1, 1, 1, 2, 2, 2, ...
        col = (node_id - 1) % 3     # 0, 1, 2, 0, 1, 2, 0, 1, 2, ...
        
        # Calculate offset from center
        lat_offset = (row - 1) * lat_delta  # Center row (1) has no offset
        lon_offset = (col - 1) * lon_delta  # Center col (1) has no offset
        
        # Apply offset to center coordinates
        latitude = center_lat + lat_offset
        longitude = center_lon + lon_offset
        
        # Store position (note that we store as (lat, lon) for the map)
        self.nodes[node_id]["pos"] = (latitude, longitude)
        
        print(f"Simulated position for Node {node_id}: ({latitude}, {longitude})")

    def simulate_node_positions(self):
        """
        Simulate node positions in a grid pattern around specific GPS coordinates
        for all nodes that don't have positions yet
        
        Centered at [24.7739578, 121.0455114] with small offsets for each node
        """
        # For each node without a position, call the single-node simulation function
        for node_id, node in self.nodes.items():
            if node["pos"] is None:  # Only position nodes that don't have positions yet
                self._simulate_position_for_node(node_id)
        
        # Redraw the map with the new positions
        self._redraw()

    def simulate_drone_movement(self):
        """Simulate drone position changes over time within a specific geographic area"""
        # Central coordinates for the simulation area (Hsinchu region)
        center_lat = 24.7739578
        center_lon = 121.0455114
        
        # Simulation range (approximately 500 meters in each direction)
        # 0.001 degrees is roughly 111 meters for latitude
        # 0.001 degrees longitude varies by latitude but is roughly 111*cos(latitude) meters
        lat_range = 0.0045  # About 500m in latitude
        lon_range = 0.0054  # About 500m in longitude at this latitude
        
        import random
        import math
        
        for node_id in self.nodes:
            if node_id in self.drone_statuses:
                # Only simulate position if we have a drone status for this node
                status = self.drone_statuses[node_id]
                
                # Get current position or initialize a new one
                current_pos = self.nodes[node_id].get("pos")
                if current_pos is None:
                    # Initialize position around the center with an offset based on node_id
                    # This distributes drones around the center point
                    offset_factor = 0.2  # Controls how spread out drones are initially
                    offset_lat = (((node_id * 17) % 10) - 5) * offset_factor * lat_range / 10
                    offset_lon = (((node_id * 23) % 10) - 5) * offset_factor * lon_range / 10
                    
                    # Set initial position
                    init_lat = center_lat + offset_lat
                    init_lon = center_lon + offset_lon
                    self.nodes[node_id]["pos"] = (init_lat, init_lon)
                    
                    # Log the initial position
                    print(f"Node {node_id} initial position: ({init_lat:.7f}, {init_lon:.7f})")
                else:
                    # Current position
                    cur_lat, cur_lon = current_pos
                    
                    # Default small random movement (for unarmed drones or no heading)
                    delta_lat = random.uniform(-0.000005, 0.000005)
                    delta_lon = random.uniform(-0.000005, 0.000005)
                    
                    # Apply movement based on drone status
                    if status.get('armed', False):
                        # Larger movement if armed
                        movement_scale = 10.0  # Increase movement speed when armed
                        
                        # Movement based on heading if available
                        heading = status.get('heading')
                        if heading is not None:
                            # Convert heading to radians and calculate direction
                            heading_rad = math.radians(heading)
                            speed = status.get('groundspeed', 0.0001)
                            if speed < 0.0001:
                                speed = 0.0001
                            
                            # Calculate movement direction
                            # Note: Heading 0 is North, 90 is East, etc.
                            # In geographic coordinates, moving North increases latitude
                            # and moving East increases longitude
                            speed_factor = speed * 0.000009  # Scale speed to coordinate changes
                            
                            # Override random movement with directed movement
                            delta_lat = speed_factor * math.cos(heading_rad)
                            delta_lon = speed_factor * math.sin(heading_rad)
                        else:
                            # If no heading but armed, make larger random movements
                            delta_lat = random.uniform(-0.00005, 0.00005) * movement_scale
                            delta_lon = random.uniform(-0.00005, 0.00005) * movement_scale
                    
                    # Calculate new position
                    new_lat = cur_lat + delta_lat
                    new_lon = cur_lon + delta_lon
                    
                    # Keep within the simulation bounds
                    new_lat = max(center_lat - lat_range, min(center_lat + lat_range, new_lat))
                    new_lon = max(center_lon - lon_range, min(center_lon + lon_range, new_lon))
                    
                    # Update position
                    self.nodes[node_id]["pos"] = (new_lat, new_lon)
                    
                    # Update position in drone status for other components
                    if status.get('position') is None:
                        status['position'] = [new_lat, new_lon]
                    else:
                        status['position'][0] = new_lat
                        status['position'][1] = new_lon
        
        # Redraw the map with new positions
        self._redraw()

    def _redraw(self):
        # Create a new map
        self.map = folium.Map(
            location=[24.7736084, 121.0415506],
            zoom_start=18,
            tiles='CartoDB positron'
        )

        # Draw connections between nodes with valid positions
        nodes_with_pos = [(id, node) for id, node in self.nodes.items()
                         if node["pos"] is not None]

        for i in range(len(nodes_with_pos)):
            for j in range(i + 1, len(nodes_with_pos)):
                node1 = nodes_with_pos[i][1]
                node2 = nodes_with_pos[j][1]
                folium.PolyLine(
                    locations=[node1["pos"], node2["pos"]],
                    color='gray',
                    weight=1.5,
                    opacity=0.6
                ).add_to(self.map)

        # Add markers for nodes with positions
        for node_id, node in self.nodes.items():
            if node["pos"] is not None:
                # Choose icon color based on master status
                icon_color = 'red' if node["is_master"] else 'blue'
                status_text = "Master" if node["is_master"] else "Node"

                # Create custom popup with detailed drone status if available
                drone_status = self.drone_statuses.get(node_id, {})

                # Basic popup information
                popup_html = f"""
                <div style="width: 250px; font-family: Arial, sans-serif;">
                    <h4 style="margin-top: 0; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
                        Node {node_id} - {'Master' if node["is_master"] else 'Regular'}
                    </h4>
                    <div style="margin: 5px 0;">
                        <b>IP:</b> 192.168.199.{node_id}<br>
                        <b>Status:</b> {node["status"]}<br>
                """

                # Add detailed drone status if available
                if drone_status:
                    # Format additional status information
                    altitude = drone_status.get('altitude', 'N/A')
                    if isinstance(altitude, (int, float)):
                        altitude = f"{altitude:.1f}m"

                    flight_mode = drone_status.get('flight_mode', 'Unknown')
                    armed = "ARMED" if drone_status.get('armed', False) else "DISARMED"

                    position = drone_status.get('position', None)
                    position_str = "Unknown"
                    if position and len(position) == 2:
                        lat, lon = position
                        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                            position_str = f"{lat:.6f}, {lon:.6f}"

                    heading = drone_status.get('heading', None)
                    heading_str = f"{heading}°" if heading is not None else "N/A"

                    groundspeed = drone_status.get('groundspeed', None)
                    groundspeed_str = f"{groundspeed:.1f} m/s" if groundspeed is not None else "N/A"

                    # Add GPS information if available
                    gps_info = drone_status.get('gps', {})
                    gps_str = "N/A"
                    if gps_info:
                        fix_type = gps_info.get('fix_type', 'Unknown')
                        satellites = gps_info.get('satellites_visible', 'Unknown')
                        gps_str = f"Fix: {fix_type}, Satellites: {satellites}"

                    # Add battery information if available
                    battery_info = drone_status.get('battery', {})
                    battery_str = "N/A"
                    if battery_info:
                        percent = battery_info.get('percentage')
                        voltage = battery_info.get('voltage')

                        battery_parts = []
                        if percent is not None:
                            battery_parts.append(f"{percent}%")
                        if voltage is not None:
                            voltage_val = voltage / 1000 if voltage > 100 else voltage  # Convert from mV if needed
                            battery_parts.append(f"{voltage_val:.2f}V")

                        if battery_parts:
                            battery_str = ", ".join(battery_parts)

                    # System status
                    system_status = drone_status.get('system_status', 'Unknown')

                    # Add the detailed drone information to popup
                    popup_html += f"""
                        <div style="margin-top: 10px; border-top: 1px solid #eee; padding-top: 5px;">
                            <b>Altitude:</b> {altitude}<br>
                            <b>Flight Mode:</b> {flight_mode}<br>
                            <b>Armed:</b> {armed}<br>
                            <b>Position:</b> {position_str}<br>
                            <b>Heading:</b> {heading_str}<br>
                            <b>Ground Speed:</b> {groundspeed_str}<br>
                            <b>GPS:</b> {gps_str}<br>
                            <b>Battery:</b> {battery_str}<br>
                            <b>System Status:</b> {system_status}<br>
                        </div>
                    """

                # Close the popup div
                popup_html += """
                    </div>
                </div>
                """

                # Add marker to map
                folium.Marker(
                    location=node["pos"],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=f"192.168.199.{node_id} - Click for details",
                    icon=folium.Icon(color=icon_color, icon=self.icons[3])
                ).add_to(self.map)



class NetworkMonitorThread(QThread):
    message_received = pyqtSignal(str)
    node_status_changed = pyqtSignal(int, str)
    node_added = pyqtSignal(int, str)
    master_changed = pyqtSignal(int)
    node_removed = pyqtSignal(int)
    master_transition_start = pyqtSignal()
    master_transition_end = pyqtSignal()
    node_status_updated = pyqtSignal(int, dict)  # node_id, status_data

    def __init__(self, parent=None):
        super().__init__(parent)
        # Updated IP addresses for outside network communication
        self.gui_host = '192.168.1.2'     # GUI's outside IP
        # self.gui_host = 'localhost'
        self.gui_port = 5567              # GUI's port
        self.handler_host = '192.168.1.1' # Handler's outside IP
        # self.handler_host = 'localhost'
        self.handler_port = 5566          # Handler's outside port

        # Create and bind socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind((self.gui_host, self.gui_port))
            logger.info(f"GUI bound to {self.gui_host}:{self.gui_port}")
        except socket.error as e:
            logger.error(f"Failed to bind GUI socket: {e}")
            raise

        # Send initial connection message
        self.send_connection_message()

    def run(self):
        self.is_running = True
        while self.is_running:
            try:
                data, addr = self.socket.recvfrom(4096)
                message = json.loads(data.decode())
                self.process_message(message)
            except Exception as e:
                logger.error(f"Error receiving message: {e}")

    def send_connection_message(self):
        """Send connection message to handler with retries"""
        max_retries = 3
        retry_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                message = {
                    'type': 'GUI_CONNECTED'
                }
                self.socket.sendto(
                    json.dumps(message).encode(),
                    (self.handler_host, self.handler_port)
                )
                logger.info(f"Sent connection message to handler (attempt {attempt + 1})")
                time.sleep(retry_delay)
                return
            except Exception as e:
                logger.error(f"Failed to send connection message (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)

    def process_message(self, message):
        msg_type = message['type']
        data = message.get('data', {})

        logger.debug(f"Received message: type={msg_type}, data={data}")

        if msg_type == 'LOG':
            self.message_received.emit(data['message'])
        elif msg_type == 'NODE_ADDED':
            logger.info(f"Adding node: IP last byte={data['ip_last_byte']}, type={data['node_type']}")
            self.node_added.emit(data['ip_last_byte'], data['node_type'])
        elif msg_type == 'NODE_STATUS':
            self.node_status_changed.emit(data['node_id'], data['status'])
        elif msg_type == 'MASTER_CHANGED':
            self.master_changed.emit(data['master_id'])
        elif msg_type == "NODE_REMOVED":
            self.node_removed.emit(data['node_id'])
        elif msg_type == "MASTER_TRANSITION_START":
            self.master_transition_start.emit()
        elif msg_type == "MASTER_TRANSITION_END":
            self.master_transition_end.emit()
        elif msg_type == 'DRONE_STATUS_UPDATE':
            node_id = data['node_id']
            # Update the node status in GUI
            self.node_status_updated.emit(node_id, data)

    def stop(self):
        logger.info("Stopping NetworkMonitorThread...")
        self.is_running = False
        # Optional: Send a message to unblock the socket if it's waiting for data
        try:
            self.socket.sendto(b'', (self.gui_host, self.gui_port))
        except Exception:
            pass  # Ignore errors during shutdown
        self.socket.close()
        logger.info("NetworkMonitorThread stopped")


class MonitorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Monitor")
        self.setMinimumSize(1000, 700)

        # Create central widget with the map
        self.network_viz = NetworkVisualizerWidget()
        self.setCentralWidget(self.network_viz)

        # Create Event Log dock widget
        self.event_log_dock = QDockWidget("Event Log", self)
        self.event_log_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.event_log_dock.setFeatures(QDockWidget.DockWidgetFloatable |
                                      QDockWidget.DockWidgetMovable)

        # Create content for Event Log dock
        event_log_widget = QWidget()
        event_log_layout = QVBoxLayout(event_log_widget)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            font-size: 14px;
            padding: 5px;
        """)
        event_log_layout.addWidget(self.log_text)
        self.event_log_dock.setWidget(event_log_widget)

        # Create Node Status dock widget
        self.node_status_dock = QDockWidget("Node Status", self)
        self.node_status_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.node_status_dock.setFeatures(QDockWidget.DockWidgetFloatable |
                                        QDockWidget.DockWidgetMovable)

        # Create content for Node Status dock
        node_status_widget = QWidget()
        node_status_layout = QVBoxLayout(node_status_widget)
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("""
            font-size: 14px;
            padding: 5px;
        """)
        node_status_layout.addWidget(self.status_text)
        self.node_status_dock.setWidget(node_status_widget)

        # Add dock widgets to the main window
        self.addDockWidget(Qt.LeftDockWidgetArea, self.node_status_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.event_log_dock)

        # Set initial sizes for the dock widgets
        self.resizeDocks([self.node_status_dock, self.event_log_dock],
                        [200, 200], Qt.Horizontal)

        # Initialize node status dictionary
        self.node_statuses = {}

        # Create a timer for simulating drone movement if no real position data
        """
        self.position_timer = QTimer(self)
        self.position_timer.timeout.connect(self.network_viz.simulate_drone_movement)
        self.position_timer.start(2000)  # Update every second
        """

        # Start monitor thread
        self.monitor_thread = NetworkMonitorThread(self)
        self.monitor_thread.message_received.connect(self.log_message)
        self.monitor_thread.node_status_changed.connect(self.update_node_status)
        self.monitor_thread.node_added.connect(self.add_node)
        self.monitor_thread.master_changed.connect(self.update_master_status)
        self.monitor_thread.node_removed.connect(self.remove_node)
        self.monitor_thread.master_transition_start.connect(self.network_viz.startMasterTransition)
        self.monitor_thread.master_transition_end.connect(self.network_viz.endMasterTransition)
        self.monitor_thread.node_status_updated.connect(self.network_viz.updateDroneStatus)
        self.monitor_thread.start()

        # Log initial message
        self.log_message("Network Monitor started successfully")
        
        # Uncomment this for testing if you don't have real position data
        QTimer.singleShot(2000, self.network_viz.simulate_node_positions)

    def update_status_display(self):
        """Update the status display text with current node information"""
        status_text = "Current Network Nodes:\n"
        status_text += "-" * 40 + "\n"

        # Format string for consistent spacing
        format_str = "{icon}  {ip:<16} | {role}\n"

        for node_id, status in sorted(self.node_statuses.items()):
            icon = "👑" if status["is_master"] else "🤖"
            ip = f"192.168.199.{node_id}"
            role = "Master" if status["is_master"] else "Regular"

            status_text += format_str.format(
                icon=icon,
                ip=ip,
                role=role
            )

        self.status_text.setText(status_text)

    def add_node(self, ip_last_byte, node_type):
        """Handle new node addition"""
        if node_type != "MONITOR":
            self.node_statuses[ip_last_byte] = {
                "is_master": False,  # Initialize all nodes as non-master
                "status": "Active"
            }
            self.network_viz.addNode(ip_last_byte, node_type)
            self.update_status_display()
            self.log_message(f"Node added: 192.168.199.{ip_last_byte} ({node_type})")

    def update_node_status(self, node_id, status):
        """Handle node status updates"""
        if node_id in self.node_statuses:
            self.node_statuses[node_id]["status"] = status
            self.network_viz.updateNodeStatus(node_id, status)
            self.update_status_display()
            self.log_message(f"Node 192.168.199.{node_id} status updated: {status}")

    def update_master_status(self, master_id):
        """Handle master node changes"""
        for node_id in self.node_statuses:
            self.node_statuses[node_id]["is_master"] = (node_id == master_id)
        self.network_viz.updateMasterStatus(master_id)
        self.update_status_display()
        self.log_message(f"Master changed to node 192.168.199.{master_id}")

    def remove_node(self, node_id):
        """Handle node removal"""
        if node_id in self.node_statuses:
            del self.node_statuses[node_id]
            self.network_viz.removeNode(node_id)
            self.update_status_display()
            self.log_message(f"Node removed: 192.168.199.{node_id}")

    def log_message(self, message):
        """Add a message to the event log with timestamp"""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_text.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        # self.position_timer.stop()  # Stop the simulation timer
        self.monitor_thread.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    try:
        window = MonitorGUI()
        window.show()
        print("\nGUI running on 192.168.1.2:5567")
        print("Connected to handler at 192.168.1.1:5566")
        sys.exit(app.exec_())
    except Exception as e:
        logger.error(f"Error starting GUI: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
