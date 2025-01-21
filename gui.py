from PyQt5.QtWidgets import (
    QApplication, 
    QMainWindow, 
    QWidget, 
    QVBoxLayout, 
    QHBoxLayout, 
    QLabel, 
    QTextEdit)
from PyQt5.QtCore import pyqtSignal, QThread
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import matplotlib.image as mpimg
import socket
import json
import sys
import time
import math
import struct
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
        
        # Load drone images
        self.leader_img = mpimg.imread('node_master.png')
        self.follower_img = mpimg.imread('node_regular.png')
        
        # Create the figure and canvas
        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        
        # Set up the layout
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Configure plot
        self.ax.set_xlim(0, 6)
        self.ax.set_ylim(0, 6)
        self.ax.set_aspect('equal')
        self.ax.axis('on')
        self.ax.grid(True)
        
        # Set ticks every 0.5m
        self.ax.set_xticks([i/2 for i in range(13)])
        self.ax.set_yticks([i/2 for i in range(13)])
        self.ax.tick_params(axis='both', which='major', labelsize=8)
        
        self._create_legend()

    def _create_legend(self):
        from matplotlib.patches import Patch
        leader_patch = Patch(color='r', label='Master Node')
        follower_patch = Patch(color='b', label='Regular Node')
        
        self.ax.legend(handles=[leader_patch, follower_patch],
                    loc='upper right', bbox_to_anchor=(1.1, 1.1))

    def _draw_drone(self, pos, is_master=False):
        """Helper method to draw a drone at the given position"""
        img = self.leader_img if is_master else self.follower_img
        imagebox = OffsetImage(img, zoom=0.1)
        ab = AnnotationBbox(imagebox, pos, frameon=False)
        self.ax.add_artist(ab)

    def addNode(self, ip_last_byte, node_type):
        node_id = ip_last_byte
        if node_type == "MONITOR":
            return
        
        # Add node without position - position will be set by simulator
        self.nodes[node_id] = {
            "pos": None,  # Position will be updated by position simulator
            "type": node_type,
            "status": "Active",
            "color": 'g',
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

    def updateNodePosition(self, node_id, x, y):
        if node_id in self.nodes:
            self.nodes[node_id]["pos"] = (x, y)
            print(f"Node {node_id} position updated: ({x:.2f}, {y:.2f})")
            self._redraw()
        else:
            print(f"Position update for unknown node: {node_id}")

    def updateMasterStatus(self, master_id):
        if self.in_transition:
            return
            
        # Reset all nodes to non-master first
        for node in self.nodes.values():
            node["is_master"] = False
            node["color"] = 'g'

        # Set the new master if one is specified
        if master_id is not None and master_id in self.nodes:
            self.nodes[master_id]["is_master"] = True
            self.nodes[master_id]["color"] = 'r'
            print(f"Updated master status: Node {master_id} is now master")
        else:
            print("No master node currently assigned")
        
        self._redraw()

    def updateNodeStatus(self, node_id, status):
        if node_id in self.nodes:
            self.nodes[node_id]["status"] = status
            if self.nodes[node_id]["is_master"]:
                self.nodes[node_id]["color"] = 'r'
            else:
                self.nodes[node_id]["color"] = 'g'
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

    def _redraw(self):
        self.ax.clear()
        
        # Configure plot
        self.ax.set_xlim(0, 6)
        self.ax.set_ylim(0, 6)
        self.ax.set_aspect('equal')
        self.ax.axis('on')
        self.ax.grid(True)
        
        # Set ticks every 0.5m
        self.ax.set_xticks([i/2 for i in range(13)])
        self.ax.set_yticks([i/2 for i in range(13)])
        self.ax.tick_params(axis='both', which='major', labelsize=8)

        # Draw connections between nodes with valid positions
        nodes_with_pos = [(id, node) for id, node in self.nodes.items() 
                         if node["pos"] is not None]
        
        for i in range(len(nodes_with_pos)):
            for j in range(i + 1, len(nodes_with_pos)):
                node1 = nodes_with_pos[i][1]
                node2 = nodes_with_pos[j][1]
                self.ax.plot([node1["pos"][0], node2["pos"][0]], 
                         [node1["pos"][1], node2["pos"][1]], 
                         color='lightgray', zorder=1)

        # Draw nodes using drone icons (only for nodes with positions)
        for node_id, node in self.nodes.items():
            if node["pos"] is not None:
                self._draw_drone(node["pos"], node["is_master"])
                
                # Add node label
                status_text = "Master" if node["is_master"] else "Node"
                self.ax.annotate(f'192.168.199.{node_id}\n({status_text})',
                            xy=node["pos"], 
                            xytext=(0, -25),
                            textcoords='offset points',
                            ha='center', 
                            va='top',    # Vertical alignment from top of text
                            color='black', 
                            bbox=dict(boxstyle='round,pad=0.5', 
                                    fc='white',    # White background
                                    ec='gray',     # Gray edge
                                    alpha=0.8),    # Slight transparency
                            zorder=3)

        self.ax.set_xlabel('x-axis(meter)')
        self.ax.set_ylabel('y-axis(meter)')
        self._create_legend()
        
        # Force a canvas update
        self.canvas.draw_idle()
        self.canvas.flush_events()


class NetworkMonitorThread(QThread):
    message_received = pyqtSignal(str)
    node_status_changed = pyqtSignal(int, str)
    node_added = pyqtSignal(int, str)
    master_changed = pyqtSignal(int)
    node_removed = pyqtSignal(int)
    master_transition_start = pyqtSignal()
    master_transition_end = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Updated IP addresses for outside network communication
        self.gui_host = '192.168.1.2'     # GUI's outside IP
        self.gui_port = 5567              # GUI's port
        self.handler_host = '192.168.1.1' # Handler's outside IP
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

    def stop(self):
        self.is_running = False
        self.socket.close()

class PositionReceiverThread(QThread):
    position_updated = pyqtSignal(int, float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = False
        self.last_positions = {}  # Dictionary to store last known positions

    def positions_different(self, node_id, x, y, z):
        """Check if the new position is different from the last known position"""
        if node_id not in self.last_positions:
            return True
            
        last_x, last_y, last_z = self.last_positions[node_id]
        # Compare with some tolerance to handle floating point imprecision
        tolerance = 0.0001
        return (abs(last_x - x) > tolerance or 
                abs(last_y - y) > tolerance or 
                abs(last_z - z) > tolerance)

    def update_last_position(self, node_id, x, y, z):
        """Store the last known position for a node"""
        self.last_positions[node_id] = (x, y, z)

    def run(self):
        self.is_running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", 17500))
        
        while self.is_running:
            try:
                data, addr = sock.recvfrom(1024)
                position_data = struct.unpack("ffff", data)

                # Extract position data
                node_id = int(position_data[0])
                x, y, z = position_data[1:4]
                
                # Check if position has changed
                if self.positions_different(node_id, x, y, z):
                    logger.info(f"Position changed - Node {node_id}: X={x:.3f}, Y={y:.3f}, Z={z:.3f}")
                    self.update_last_position(node_id, x, y, z)
                    self.position_updated.emit(node_id, x, y)
                else:
                    logger.debug(f"Skipping update - No position change for Node {node_id}")
                    
            except Exception as e:
                logger.error(f"Error receiving position data: {e}")
                
        sock.close()
        
    def stop(self):
        self.is_running = False

class MonitorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Monitor")
        
        # screen = QApplication.primaryScreen().geometry()
        # self.setGeometry(screen)
        self.setFixedSize(800, 640)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Create left panel for event log
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        layout.addWidget(left_panel)

        # Add event log to left panel
        log_label = QLabel("Event Log")
        log_label.setStyleSheet("""
            font-weight: bold;
            font-size: 16px;
            padding: 5px;
            background-color: #fcba03;
            border-radius: 5px;
        """)
        self.log_text = QTextEdit()
        self.log_text.setStyleSheet("""
            font-size: 16px;
            padding: 5px;
        """)
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumWidth(150)
        left_layout.addWidget(log_label)
        left_layout.addWidget(self.log_text)

        # Create network visualizer
        self.network_viz = NetworkVisualizerWidget()
        layout.addWidget(self.network_viz)
        layout.setStretch(0, 1)  # Left panel takes 1 part
        layout.setStretch(1, 3)  # Network visualizer takes 3 parts

        # Start monitor thread
        self.monitor_thread = NetworkMonitorThread(self)
        self.monitor_thread.message_received.connect(self.log_message)
        self.monitor_thread.node_status_changed.connect(self.network_viz.updateNodeStatus)
        self.monitor_thread.node_added.connect(self.network_viz.addNode)
        self.monitor_thread.master_changed.connect(self.network_viz.updateMasterStatus)
        self.monitor_thread.node_removed.connect(self.network_viz.removeNode)
        self.monitor_thread.master_transition_start.connect(self.network_viz.startMasterTransition)
        self.monitor_thread.master_transition_end.connect(self.network_viz.endMasterTransition)
        self.monitor_thread.start()

        # Start position receiver thread
        self.position_thread = PositionReceiverThread()
        self.position_thread.position_updated.connect(self.network_viz.updateNodePosition)
        self.position_thread.start()
        
    def log_message(self, message):
        self.log_text.append(message)

    def closeEvent(self, event):
        self.monitor_thread.stop()
        self.position_thread.stop()
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