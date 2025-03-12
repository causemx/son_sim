import folium
import io
import socket
import json
import sys
import time
import logging
import random
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QDockWidget
)
from PyQt5.QtCore import (
    pyqtSignal,
    QThread,
    Qt
)
from PyQt5.QtWebEngineWidgets import QWebEngineView


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

        self.nodes[node_id] = {
            "pos": None,
            "type": node_type,
            "status": "Active",
            "color": 'blue',
            "ip_last_byte": ip_last_byte,
            "is_master": node_id == 1,
            "last_seen": time.time()
        }

        self._redraw()

    def removeNode(self, node_id):
        if node_id in self.nodes:
            if self.nodes[node_id]["pos"]:
                self.last_positions[node_id] = self.nodes[node_id]["pos"]
            del self.nodes[node_id]
            self._redraw()


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

            # Update position if provided in status
            if 'position' in status_data and status_data['position']:
                lat, lon = status_data['position']
                # Convert GPS coordinates to map coordinates
                map_y, map_x = lat, lon  # Simplified mapping for demo
                self.nodes[node_id]["pos"] = (map_y, map_x)

            # Always update the node's status text
            status_text = "Active"
            if status_data.get('armed', False):
                status_text = f"ARMED [{status_data.get('flight_mode', 'UNKNOWN')}]"
            else:
                status_text = f"DISARMED [{status_data.get('flight_mode', 'UNKNOWN')}]"

            self.nodes[node_id]["status"] = status_text

            # Update last seen timestamp
            self.nodes[node_id]["last_seen"] = time.time()

            # Always redraw regardless of position or status changes
            self._redraw()

    def generate_random_position(self):
        """Generate a random position within the specified latitude and longitude ranges"""
        # Latitude range: [24.7727962, 24.7732732]
        # Longitude range: [121.0449733, 121.0452793]
        lat = random.uniform(24.7727962, 24.7732732)
        lon = random.uniform(121.0449733, 121.0452793)
        return (lat, lon)

    def assign_positions_to_nodes(self, nodes):
        """Assign positions to all nodes"""
        print("[DEBUG] Assigning forced positions to nodes")
        
        for node_id, node in nodes.items():
            # Generate a position if the node doesn't have one
            if node["pos"] is None:
                node["pos"] = self.generate_random_position()
                print(f"[DEBUG] Assigned new position to Node {node_id}: {node['pos']}")
            else:
                # If the node already has a position, make sure it's within our bounds
                current_lat, current_lon = node["pos"]
                if (current_lat < 24.7727962 or current_lat > 24.7732732 or
                    current_lon < 121.0449733 or current_lon > 121.0452793):
                    node["pos"] = self.generate_random_position()
                    print(f"[DEBUG] Replaced out-of-bounds position for Node {node_id} with: {node['pos']}")
        
        return nodes

    def _redraw(self):
        print("[DEBUG] Starting map redraw...")
        
        # Log all nodes and their positions
        print("[DEBUG] Current nodes status before forcing positions:")
        for node_id, node in self.nodes.items():
            pos_status = f"{node['pos']}" if node['pos'] is not None else "No position"
            print(f"[DEBUG]   Node {node_id}: {pos_status}, Master: {node['is_master']}, Status: {node['status']}")
        
        # Create a new map
        self.map = folium.Map(
            location=[24.7730347, 121.0451263],  # Center of our area
            zoom_start=19,
            tiles='CartoDB positron'
        )

        # TODO: Force node position to be simulated position
        # Implementation of the TODO - force positions for all nodes
        # self.nodes = self.assign_positions_to_nodes(self.nodes)
        
        # Log all nodes and their positions after forcing
        print("[DEBUG] Current nodes status after forcing positions:")
        for node_id, node in self.nodes.items():
            pos_status = f"{node['pos']}" if node['pos'] is not None else "Still no position"
            print(f"[DEBUG]   Node {node_id}: {pos_status}, Master: {node['is_master']}, Status: {node['status']}")

        # Draw connections between nodes with valid positions
        nodes_with_pos = [(id, node) for id, node in self.nodes.items()
                        if node["pos"] is not None]
        
        print(f"[DEBUG] Found {len(nodes_with_pos)} nodes with valid positions")

        for i in range(len(nodes_with_pos)):
            for j in range(i + 1, len(nodes_with_pos)):
                node1 = nodes_with_pos[i][1]
                node2 = nodes_with_pos[j][1]
                node1_id = nodes_with_pos[i][0]
                node2_id = nodes_with_pos[j][0]
                print(f"[DEBUG] Drawing connection between Node {node1_id} {node1['pos']} and Node {node2_id} {node2['pos']}")
                folium.PolyLine(
                    locations=[node1["pos"], node2["pos"]],
                    color='gray',
                    weight=1.5,
                    opacity=0.6
                ).add_to(self.map)

        # Add markers for nodes with positions
        for node_id, node in self.nodes.items():
            if node["pos"] is not None:
                print(f"[DEBUG] Adding marker for Node {node_id} at position {node['pos']}")
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
                    icon=folium.Icon(color=icon_color, icon=self.icons[9])
                ).add_to(self.map)
            else:
                print(f"[DEBUG] Node {node_id} still has no position after forcing, skipping marker")

        # Display the map
        data = io.BytesIO()
        self.map.save(data, close_file=False)
        self.web_view.setHtml(data.getvalue().decode())
        print("[DEBUG] Map redraw completed")


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