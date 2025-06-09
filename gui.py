import folium
import io
import json
import sys
import time
import logging
import random
import threading
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QDockWidget,
    QPushButton,
    QGroupBox,
    QGridLayout,
    QLabel,
    QMessageBox
)
from PyQt5.QtCore import (
    pyqtSignal,
    pyqtSlot,
    QThread,
    QObject,
    Qt
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel

from libs import drone_v2x


# Configure logging to only show console output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# Global initialization status
_init_status = None
_init_message = ""

def init_callback(status: int, message: str):
    """Callback function that captures the init status"""
    global _init_status, _init_message
    
    _init_status = status
    _init_message = message
    
    if status == 1:
        logger.info(f"Init success: {message}")
    else:
        logger.warning(f"Init status {status}: {message}")

def wait_for_initialization():
    """Wait for initialization to complete or timeout"""
    logger.info("Waiting for drone_v2x initialization...")
    
    # Set the callback
    drone_v2x.set_init_callback(init_callback)
    
    # Start initialization
    drone_v2x.init()
    
     # Wait for initialization to complete
    while _init_status is None or _init_status == 0:
        print("Initializing drone_v2x ing...")
        time.sleep(1)  # Wait 1 second between status checks
    
    # Check final result
    if _init_status == 1:
        print("Drone V2X initialization successful!")
        return True
    else:
        print(f"Drone V2X initialization failed: {_init_message}")
        return False

class JSChannel(QObject):
    @pyqtSlot(str)
    def logMessage(self, message):
        pass
        # print(f"[JS DEBUG] {message}")

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
        self.web_channel = QWebChannel()
        self.web_view.page().setWebChannel(self.web_channel)
        self.jsDebugger = JSChannel()
        self.web_channel.registerObject("jsDebugger", self.jsDebugger)
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
            zoom_start=18,
            max_zoom=22,
            rotate=True,
            rotateControl={ "closeOnZeroBearing": False },
            touchRotate=True,
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

        # Add scripts to control markers - Updated for 3 nodes
        self.map._id = 'folium'  # Required for the map to be recognized by the script
        script = '''<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
        <script src="https://unpkg.com/leaflet-rotate@0.2.8/dist/leaflet-rotate-src.js"></script>
        <script>
        const startTime = Date.now();
        var polylines;
        const countTimer = setInterval(() => {
            if (map_folium) {
                updateNodes = doUpdateNodes
                clearInterval(countTimer);
                logMessage("Map readied in " + (Date.now() - startTime) + "ms");
                polylines  = L.layerGroup().addTo(map_folium);
            }
        }, 10);
        new QWebChannel(qt.webChannelTransport, c => (window.logMessage = c.objects.jsDebugger.logMessage));

        var droneMarkers = [];
        const masterIcon = L.AwesomeMarkers.icon({
                icon: 'glyphicon-plane',
                markerColor: 'red'
            });
        const regularIcon = L.AwesomeMarkers.icon({
                icon: 'glyphicon-plane',
                markerColor: 'blue'
            });
        
        // Initialize markers for nodes 13, 14 (node IDs from your V2X setup)
        const nodeIds = [13, 14];
        for (let nodeId of nodeIds) {
            var marker = L.marker([24.7736084, 121.0415506]);
            marker.bindPopup(() => markerPopup(nodeId));
            droneMarkers[nodeId] = marker;
        }

        function markerPopup(node_id) {
            const node = droneMarkers[node_id].node;
            let content = '<div class="markerpopup" style="width: 250px; font-family: Arial, sans-serif;">';
            if (node) {
                content += `<h4 style="margin-top: 0; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
                        Node ${node_id} - ${node.is_master ? 'Master' : 'Regular'}
                    </h4>
                    <div style="margin: 5px 0;">
                        <b>Group/ID:</b> ${node_id === 11 ? '1/11' : '11/' + node_id}<br>
                        <b>Status:</b> ${node.status}<br>`;
                const droneStatus = node.drone_status;
                logMessage(droneStatus)
                if (droneStatus) {
                    let altitude = droneStatus.altitude ? `${droneStatus.altitude.toFixed(1)}m` : 'N/A';
                    let flightMode = droneStatus.flight_mode || 'Unknown';
                    let armed = droneStatus.armed ? 'ARMED' : 'DISARMED';
                    
                    let positionStr = 'Unknown';
                    if (droneStatus.position && droneStatus.position.length === 2) {
                        let [lat, lon] = droneStatus.position;
                        positionStr = `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
                    }
                    
                    let headingStr = droneStatus.heading ? `${droneStatus.heading}°` : 'N/A';
                    let groundspeedStr = droneStatus.groundspeed ? `${droneStatus.groundspeed.toFixed(1)} m/s` : 'N/A';
                    
                    let gps = droneStatus.gps || {};
                    let gpsStr = gps.fix_type ? `Fix: ${gps.fix_type}, Satellites: ${gps.satellites_visible}` : 'N/A';
                    
                    let battery = droneStatus.battery || {};
                    let batteryStr = 'N/A';
                    if (battery.percentage !== undefined || battery.voltage !== undefined) {
                        let voltage = battery.voltage > 100 ? (battery.voltage / 1000).toFixed(2) : battery.voltage;
                        batteryStr = `${battery.percentage || ''}% ${voltage ? voltage + 'V' : ''}`.trim();
                    }
                    
                    let systemStatus = droneStatus.system_status || 'Unknown';
                    
                    content += `
                        <div style="margin-top: 10px; border-top: 1px solid #eee; padding-top: 5px;">
                            <b>Altitude:</b> ${altitude}<br>
                            <b>Flight Mode:</b> ${flightMode}<br>
                            <b>Armed:</b> ${armed}<br>
                            <b>Position:</b> ${positionStr}<br>
                            <b>Heading:</b> ${headingStr}<br>
                            <b>Ground Speed:</b> ${groundspeedStr}<br>
                            <b>GPS:</b> ${gpsStr}<br>
                            <b>Battery:</b> ${batteryStr}<br>
                            <b>System Status:</b> ${systemStatus}<br>
                        </div>
                    `;
                }
            }
            logMessage(content + '</div></div>');
            return content + '</div></div>';
        }

        var updateNodes = function(nodesJson) { logMessage("updateJson: map not ready."); };

        function doUpdateNodes(nodesJson) {
            logMessage("doUpdateNodes: " + nodesJson);
            const nodes = JSON.parse(nodesJson);
            const nodeIds = [11, 13, 14];
            
            for (let nodeId of nodeIds) {
                droneMarkers[nodeId].node = nodes[nodeId];
                if (nodes[nodeId] && nodes[nodeId].pos) {
                    droneMarkers[nodeId].setLatLng(nodes[nodeId].pos);
                    if (droneMarkers[nodeId].isPopupOpen()) {
                        droneMarkers[nodeId].setPopupContent(markerPopup(nodeId));
                    }
                    droneMarkers[nodeId].setIcon(nodes[nodeId].is_master ? masterIcon : regularIcon);
                    droneMarkers[nodeId].addTo(map_folium);
                } else {
                    if (droneMarkers[nodeId].isPopupOpen()) {
                        droneMarkers[nodeId].closePopup();
                    }
                    map_folium.removeLayer(droneMarkers[nodeId]);
                    delete nodes[nodeId];
                }
            }

            polylines.clearLayers();
            const activeNodes = Object.keys(nodes).map(id => parseInt(id));
            for (let i = 0; i < activeNodes.length; i++) {
                for (let j = i + 1; j < activeNodes.length; j++) {
                    let nodeA = activeNodes[i];
                    let nodeB = activeNodes[j];
                    if (nodes[nodeA] && nodes[nodeB] && nodes[nodeA].pos && nodes[nodeB].pos) {
                        L.polyline([nodes[nodeA].pos, nodes[nodeB].pos], {
                            color: 'gray',
                            weight: 1.5,
                            opacity: 0.6
                        }).addTo(polylines);
                    }
                }
            }
        }
        </script>
        '''
        self.map.get_root().html.add_child(folium.Element(script))

        # Display the map
        data = io.BytesIO()
        self.map.save(data, close_file=False)
        self.web_view.setHtml(data.getvalue().decode())

    def addNode(self, node_id, node_type):
        if node_type == "MONITOR":
            return

        # Map node IDs to match your V2X setup (including handler as node 11)
        self.nodes[node_id] = {
            "pos": None,
            "type": node_type,
            "status": "Active",
            "color": 'blue',
            "node_id": node_id,
            "is_master": node_id == 11,  # Handler (Node 11) starts as master
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
        # print("[DEBUG] Starting map redraw...")

        # Update the map with the new node positions
        self.web_view.page().runJavaScript("updateNodes('" + json.dumps(self.nodes) + "')")
        return


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
        # V2X communication settings - Updated for your 3-node setup
        self.gui_group = 1     # GUI's group
        self.gui_id = 1        # GUI's ID
        self.handler_group = 1  # Handler's group (changed from 11 to 1)
        self.handler_id = 11     # Handler's ID (changed from 12 to 11)

        # Send initial connection message
        self.send_connection_message()

    def run(self):
        self.is_running = True
        while self.is_running:
            try:
                # Check for messages from handler using V2X communication
                try:
                    data, addr = drone_v2x.recv(1400)
                    message = json.loads(data.decode().rstrip('\x00'))
                    self.process_message(message)
                except Exception as e:
                    # No message or error
                    if str(e) != "timed out":  # Ignore timeout errors
                        logger.error(f"Error receiving V2X message: {e}")

                time.sleep(0.01)  # Short sleep to prevent CPU overuse

            except Exception as e:
                logger.error(f"Error in NetworkMonitorThread: {e}")
                time.sleep(0.1)

    def send_connection_message(self):
        """Send connection message to handler with retries"""
        max_retries = 3
        retry_delay = 1.0  # seconds

        for attempt in range(max_retries):
            try:
                message = {
                    'type': 'GUI_CONNECTED',
                    'from': self.gui_id
                }
                json_message = json.dumps(message)
                drone_v2x.send(json_message, (self.handler_group, self.handler_id))
                logger.info(f"Sent connection message to handler (attempt {attempt + 1})")
                time.sleep(retry_delay)
                return
            except Exception as e:
                logger.error(f"Failed to send connection message (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
    
    def send_command(self, command_type, target_node=None, params=None):
        """Send a command to the handler using V2X communication"""
        try:
            message = {
                'type': 'GUI_COMMAND',
                'from': self.gui_id,
                'data': {
                    'command_type': command_type
                }
            }
            
            # Add target node if specified
            if target_node is not None:
                message['data']['target_node'] = target_node
                
            # Add any additional parameters
            if params:
                message['data'].update(params)
                
            json_message = json.dumps(message)
            drone_v2x.send(json_message, (self.handler_group, self.handler_id))
            logger.info(f"Sent command: {command_type} to handler")
            return True
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return False

    def process_message(self, message):
        msg_type = message['type']
        data = message.get('data', {})

        logger.debug(f"Received message: type={msg_type}, data={data}")

        if msg_type == 'LOG':
            self.message_received.emit(data['message'])
        elif msg_type == 'NODE_ADDED':
            logger.info(f"Adding node: Node ID={data['node_id']}, type={data['node_type']}")
            self.node_added.emit(data['node_id'], data['node_type'])
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
        logger.info("NetworkMonitorThread stopped")


class CommandsPanel(QWidget):
    def __init__(self, monitor_thread, parent=None):
        super().__init__(parent)
        self.monitor_thread = monitor_thread
        self.selected_node = None
        
        # Main layout
        layout = QVBoxLayout(self)
        
        # Create a group for node selection
        node_group = QGroupBox("Node Selection")
        node_layout = QGridLayout()
        
        self.node_label = QLabel("Selected Node: None")
        node_layout.addWidget(self.node_label, 0, 0, 1, 2)
        
        # Add buttons for node selection
        self.node_selector_label = QLabel("Select Node:")
        node_layout.addWidget(self.node_selector_label, 1, 0, 1, 3)
        
        # Add buttons for your specific node IDs (11, 13, 14) including handler
        node_ids = [11, 12, 13]
        for i, node_id in enumerate(node_ids):
            btn_text = f"Node {node_id}"
            if node_id == 11:
                btn_text += " (Handler)"
            btn = QPushButton(btn_text)
            btn.clicked.connect(lambda checked, node_id=node_id: self.select_node(node_id))
            node_layout.addWidget(btn, 2, i)
        
        # Add "All Nodes" button
        all_nodes_btn = QPushButton("All Nodes")
        all_nodes_btn.clicked.connect(lambda: self.select_node("all"))
        all_nodes_btn.setStyleSheet("background-color: #d0e0ff;")  # Light blue background to highlight
        node_layout.addWidget(all_nodes_btn, 3, 0, 1, 3)  # Span across all three columns
            
        node_group.setLayout(node_layout)
        layout.addWidget(node_group)
        
        # Create a group for drone commands
        drone_group = QGroupBox("Drone Commands")
        drone_layout = QVBoxLayout()
        
        # Arm/Disarm buttons
        arm_btn = QPushButton("Arm Drone")
        arm_btn.clicked.connect(self.arm_drone)
        drone_layout.addWidget(arm_btn)
        
        disarm_btn = QPushButton("Disarm Drone")
        disarm_btn.clicked.connect(self.disarm_drone)
        drone_layout.addWidget(disarm_btn)
        
        # Add description label for default altitude
        altitude_info = QLabel("Default altitude is 6m")
        altitude_info.setStyleSheet("color: #666666; font-style: italic; font-size: 11px;")
        drone_layout.addWidget(altitude_info)

        # Takeoff and E-Stop buttons
        takeoff_btn = QPushButton("Takeoff Drone")
        takeoff_btn.clicked.connect(self.takeoff_drone)
        drone_layout.addWidget(takeoff_btn)
        
        estop_btn = QPushButton("E-Stop")
        estop_btn.setStyleSheet("background-color: #ffcccc; font-weight: bold;")  # Light red background
        estop_btn.clicked.connect(self.emergency_stop)
        drone_layout.addWidget(estop_btn)
        
        # Flight mode buttons (grid layout)
        flight_mode_group = QGroupBox("Flight Modes")
        flight_mode_layout = QGridLayout()
        
        # Common flight modes
        flight_modes = ["GUIDED", "AUTO", "LOITER", "RTL", "LAND", "STABILIZE"]
        for i, mode in enumerate(flight_modes):
            btn = QPushButton(mode)
            btn.clicked.connect(lambda checked, mode=mode: self.set_flight_mode(mode))
            flight_mode_layout.addWidget(btn, i // 3, i % 3)
            
        flight_mode_group.setLayout(flight_mode_layout)
        drone_layout.addWidget(flight_mode_group)
        
        drone_group.setLayout(drone_layout)
        layout.addWidget(drone_group)
        
        # Create a group for network commands
        network_group = QGroupBox("Network Commands")
        network_layout = QVBoxLayout()
        
        # Network-wide command buttons
        force_master_btn = QPushButton("Force Master Election")
        force_master_btn.clicked.connect(self.force_master_election)
        network_layout.addWidget(force_master_btn)
        
        refresh_btn = QPushButton("Refresh Map")
        refresh_btn.clicked.connect(self.refresh_map)
        network_layout.addWidget(refresh_btn)
        
        network_group.setLayout(network_layout)
        layout.addWidget(network_group)
        
        # Add a spacer at the bottom
        layout.addStretch()
        
        # Set styling
        self.setStyleSheet("""
            QPushButton {
                padding: 5px;
                font-size: 12px;
                background-color: #f0f0f0;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid gray;
                border-radius: 5px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
        """)
    
    def select_node(self, node_id):
        """Select a node for command targeting"""
        self.selected_node = node_id
        if node_id == "all":
            self.node_label.setText("Selected Node: All Nodes")
            logger.info("Selected all nodes for command targeting")
        else:
            self.node_label.setText(f"Selected Node: {node_id}")
            logger.info(f"Selected node {node_id} for command targeting")
    
    def arm_drone(self):
        """Send arm command to the selected drone"""
        if self.selected_node is None:
            self.show_error("Please select a node first")
            return
            
        if self.selected_node == "all":
            reply = QMessageBox.question(
                self, 
                'Confirm Multiple Arm',
                'Are you sure you want to arm ALL drones?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                logger.info("Sending ARM command to all nodes")
                self.monitor_thread.send_command("ARM_DRONE", "all")
        else:
            logger.info(f"Sending ARM command to node {self.selected_node}")
            self.monitor_thread.send_command("ARM_DRONE", self.selected_node)
    
    def disarm_drone(self):
        """Send disarm command to the selected drone"""
        if self.selected_node is None:
            self.show_error("Please select a node first")
            return
            
        if self.selected_node == "all":
            reply = QMessageBox.question(
                self, 
                'Confirm Multiple Disarm',
                'Are you sure you want to disarm ALL drones?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                logger.info("Sending DISARM command to all nodes")
                self.monitor_thread.send_command("DISARM_DRONE", "all")
        else:
            logger.info(f"Sending DISARM command to node {self.selected_node}")
            self.monitor_thread.send_command("DISARM_DRONE", self.selected_node)
    
    def set_flight_mode(self, mode):
        """Send flight mode command to the selected drone"""
        if self.selected_node is None:
            self.show_error("Please select a node first")
            return
            
        if self.selected_node == "all":
            reply = QMessageBox.question(
                self, 
                'Confirm Multiple Mode Change',
                f'Are you sure you want to set ALL drones to {mode} mode?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                logger.info(f"Setting flight mode {mode} for all nodes")
                self.monitor_thread.send_command("SET_FLIGHT_MODE", "all", {'mode': mode})
        else:
            logger.info(f"Setting flight mode {mode} for node {self.selected_node}")
            self.monitor_thread.send_command("SET_FLIGHT_MODE", self.selected_node, {'mode': mode})
    

    def force_master_election(self):
        """Force a new master election in the network"""
        logger.info("Forcing master re-election")
        self.monitor_thread.send_command("FORCE_MASTER_ELECTION")
    
    def refresh_map(self):
        """Refresh the network map"""
        logger.info("Refreshing network map")
        self.monitor_thread.send_command("REFRESH_MAP")
    
    def takeoff_drone(self):
        """Send takeoff command to the selected drone"""
        if self.selected_node is None:
            self.show_error("Please select a node first")
            return
            
        # Default altitude
        altitude = 6.0
            
        if self.selected_node == "all":
            reply = QMessageBox.question(
                self, 
                'Confirm Multiple Takeoff',
                f'Are you sure you want ALL drones to takeoff to {altitude}m?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                logger.info(f"Sending TAKEOFF command to all nodes (altitude: {altitude}m)")
                self.monitor_thread.send_command("TAKEOFF", "all", {'altitude': altitude})
        else:
            logger.info(f"Sending TAKEOFF command to node {self.selected_node} (altitude: {altitude}m)")
            self.monitor_thread.send_command("TAKEOFF", self.selected_node, {'altitude': altitude})
    
    def emergency_stop(self):
        """Send emergency stop command to the selected drone"""
        if self.selected_node is None:
            self.show_error("Please select a node first")
            return
            
        # E-Stop is a critical command, so always confirm
        confirm_msg = "Are you sure you want to emergency stop "
        confirm_msg += "ALL drones?" if self.selected_node == "all" else f"drone {self.selected_node}?"
        
        reply = QMessageBox.warning(
            self, 
            'Confirm Emergency Stop',
            confirm_msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.selected_node == "all":
                logger.info("Sending EMERGENCY_STOP command to all nodes")
                self.monitor_thread.send_command("EMERGENCY_STOP", "all")
            else:
                logger.info(f"Sending EMERGENCY_STOP command to node {self.selected_node}")
                self.monitor_thread.send_command("EMERGENCY_STOP", self.selected_node)
    

    def show_error(self, message):
        """Show error message dialog"""
        QMessageBox.critical(self, "Error", message)


class MonitorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Monitor - 3 Node System")
        self.setMinimumSize(1200, 700)

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
            padding: 8px;
            line-height: 1.4;
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
            padding: 8px;
            line-height: 1.4;
        """)
        node_status_layout.addWidget(self.status_text)
        self.node_status_dock.setWidget(node_status_widget)

        # Create Commands dock widget on the right side
        self.commands_dock = QDockWidget("Commands", self)
        self.commands_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.commands_dock.setFeatures(QDockWidget.DockWidgetFloatable |
                                     QDockWidget.DockWidgetMovable)
        
        # Start monitor thread
        self.monitor_thread = NetworkMonitorThread(self)
        
        # Create the commands panel and add it to the dock
        self.commands_panel = CommandsPanel(self.monitor_thread)
        self.commands_dock.setWidget(self.commands_panel)
        
        # Add dock widgets to the main window
        self.addDockWidget(Qt.LeftDockWidgetArea, self.node_status_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.event_log_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.commands_dock)

        # Set initial sizes for the dock widgets
        self.resizeDocks([self.node_status_dock, self.event_log_dock],
                        [300, 300], Qt.Horizontal)
        self.resizeDocks([self.commands_dock], [250], Qt.Horizontal)

        # Initialize node status dictionary
        self.node_statuses = {}

        # Connect monitor thread signals
        self.monitor_thread.message_received.connect(self.log_message)
        self.monitor_thread.node_status_changed.connect(self.update_node_status)
        self.monitor_thread.node_added.connect(self.add_node)
        self.monitor_thread.master_changed.connect(self.update_master_status)
        self.monitor_thread.node_removed.connect(self.remove_node)
        self.monitor_thread.master_transition_start.connect(self.network_viz.startMasterTransition)
        self.monitor_thread.master_transition_end.connect(self.network_viz.endMasterTransition)
        self.monitor_thread.node_status_updated.connect(self.filter_existing_nodes)
        self.monitor_thread.start()

        # Log initial message
        self.log_message("Network Monitor started successfully - 3 Node System (Including Handler)")
        self.log_message("Handler: Group 1, ID 11 (Controllable)")
        self.log_message("Nodes: 13, 14")

    def filter_existing_nodes(self, node_id, status):
        if node_id not in self.node_statuses:
            self.add_node(node_id, 'NODE')
        else:
            self.monitor_thread.node_status_updated.disconnect(self.filter_existing_nodes)
            self.monitor_thread.node_status_updated.connect(self.network_viz.updateDroneStatus)
        self.network_viz.updateDroneStatus(node_id, status)

    def update_status_display(self):
        """Update the status display text with current node information"""
        status_text = "Current Network Nodes:\n"
        status_text += "-" * 40 + "\n"

        # Format string for consistent spacing
        format_str = "{icon}  {id:<8} | {role}\n"

        for node_id, status in sorted(self.node_statuses.items()):
            icon = "🐔" if status["is_master"] else "🐣"
            node_display = f"Node {node_id}"
            if node_id == 11:
                node_display += " (Handler)"
            role = "Master" if status["is_master"] else "Regular"

            status_text += format_str.format(
                icon=icon,
                id=node_display,
                role=role
            )

        self.status_text.setText(status_text)

    def add_node(self, node_id, node_type):
        """Handle new node addition"""
        if node_type != "MONITOR":
            self.node_statuses[node_id] = {
                "is_master": node_id == 11,  # Handler (Node 11) starts as master
                "status": "Active"
            }
            self.network_viz.addNode(node_id, node_type)
            self.update_status_display()
            node_display = f"Node {node_id}"
            if node_id == 11:
                node_display += " (Handler)"
            self.log_message(f"Node added: {node_display} ({node_type})")

    def update_node_status(self, node_id, status):
        """Handle node status updates"""
        if node_id in self.node_statuses:
            self.node_statuses[node_id]["status"] = status
            self.network_viz.updateNodeStatus(node_id, status)
            self.update_status_display()
            self.log_message(f"Node {node_id} status updated: {status}")

    def update_master_status(self, master_id):
        """Handle master node changes"""
        for node_id in self.node_statuses:
            self.node_statuses[node_id]["is_master"] = (node_id == master_id)
        self.network_viz.updateMasterStatus(master_id)
        self.update_status_display()
        self.log_message(f"Master changed to node {master_id}")

    def remove_node(self, node_id):
        """Handle node removal"""
        if node_id in self.node_statuses:
            del self.node_statuses[node_id]
            self.network_viz.removeNode(node_id)
            self.update_status_display()
            self.log_message(f"Node removed: Node {node_id}")

    def log_message(self, message):
        """Add a message to the event log with timestamp"""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_text.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        self.monitor_thread.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    try:

        # Wait for initialization before starting GUI
        if not wait_for_initialization():
            print("Failed to initialize drone_v2x. GUI will not start.")
            return

        window = MonitorGUI()
        window.show()
        print("\nGUI running with V2X communication:")
        print("GUI: Group 1, ID 1")
        print("Connected to handler at Group 1, ID 11")
        print("Controllable nodes: 11 (Handler), 13, 14")
        sys.exit(app.exec_())
    except Exception as e:
        logger.error(f"Error starting GUI: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()