from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QTextEdit)
from PyQt5.QtCore import pyqtSignal, QThread
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
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
        self.setMinimumSize(400, 300)
        self.nodes = {}
        self.last_heartbeat = {}
        self.center_x = 2.5
        self.center_y = 2.5
        self.radius = 1.5
        self.last_positions = {}  # Store last known positions for each node
        
        # Create the figure and canvas
        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        
        # Set up the layout
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Configure plot
        self.ax.set_xlim(0, 5)
        self.ax.set_ylim(0, 5)
        self.ax.set_aspect('equal')
        self.ax.axis('on')
        self.ax.grid(True)
        
        self._create_legend()


    def _create_legend(self):
        master_patch = mpatches.Patch(color='r', label='Master Node')
        active_patch = mpatches.Patch(color='g', label='Active Node')
        inactive_patch = mpatches.Patch(color='gray', label='Inactive Node')
        
        self.ax.legend(handles=[master_patch, active_patch, inactive_patch],
                      loc='upper right', bbox_to_anchor=(1.1, 1.1))

    def addNode(self, port, node_type):
        node_id = port % 1000
        if node_type == "MONITOR":
            return
            
        # Check if we have a last known position for this node
        if node_id in self.last_positions:
            x, y = self.last_positions[node_id]
        else:
            # Calculate default position using circular layout
            num_nodes = len([n for n in self.nodes.values() if n["type"] != "MONITOR"])
            angle = (num_nodes * 2 * math.pi) / 3
            x = self.center_x + self.radius * math.cos(angle)
            y = self.center_y + self.radius * math.sin(angle)

        pos = (x, y)
        self.nodes[node_id] = {
            "pos": pos,
            "type": node_type,
            "status": "Active",
            "color": 'g',
            "port": port,
            "is_master": False,
            "last_seen": time.time()
        }

        logger.info(f"Added new node: ID={node_id}, Type={node_type}, Port={port}, Position=({x:.3f}, {y:.3f})")
        self._redraw()


    def updateNodePosition(self, node_id, x, y):
        """Update node position based on received coordinates"""
        # Store the position for future reference
        self.last_positions[node_id] = (x, y)
        
        if node_id in self.nodes:
            old_pos = self.nodes[node_id]["pos"]
            self.nodes[node_id]["pos"] = (x, y)
            
            logger.debug(f"Node {node_id} visualization position updated:")
            logger.debug(f"  Old position: ({old_pos[0]:.3f}, {old_pos[1]:.3f})")
            logger.debug(f"  New position: ({x:.3f}, {y:.3f})")
            
            self._redraw()
        else:
            logger.info(f"Storing position for future node: {node_id} at ({x:.3f}, {y:.3f})")

    def updateMasterStatus(self, master_id):
        # logger.info(f"Updating master status: New master ID = {master_id}")

        for node in self.nodes.values():
            if node["status"] == "Active":
                node["is_master"] = False
                node["color"] = 'g'

        if master_id in self.nodes and self.nodes[master_id]["status"] == "Active":
            self.nodes[master_id]["is_master"] = True
            self.nodes[master_id]["color"] = 'r'
        self._redraw()

    def updateNodeStatus(self, node_id, status):
        if node_id in self.nodes:
            old_status = self.nodes[node_id]["status"]
            self.nodes[node_id]["status"] = status
            
            if status == "Active":
                if self.nodes[node_id]["is_master"]:
                    self.nodes[node_id]["color"] = 'r'
                else:
                    self.nodes[node_id]["color"] = 'g'
                self.nodes[node_id]["last_seen"] = time.time()
            else:
                self.nodes[node_id]["color"] = 'gray'
                self.nodes[node_id]["is_master"] = False
            
            if old_status == "Active" and status != "Active" and self.nodes[node_id]["is_master"]:
                self.updateMasterStatus(None)
            
            self._redraw()

    def _redraw(self):
        self.ax.clear()
        self.ax.set_xlim(0, 5)
        self.ax.set_ylim(0, 5)
        self.ax.set_aspect('equal')
        self.ax.axis('on')
        self.ax.grid(True)

        # Draw connections between active nodes
        active_nodes = [(nid, node) for nid, node in self.nodes.items() 
                       if node["status"] == "Active"]
        
        # Log node positions before drawing
        logger.debug("Active node positions:")
        for nid, node in active_nodes:
            logger.debug(f"Node {nid}: pos={node['pos']}")
        
        for i in range(len(active_nodes)):
            for j in range(i + 1, len(active_nodes)):
                node1 = active_nodes[i][1]
                node2 = active_nodes[j][1]
                self.ax.plot([node1["pos"][0], node2["pos"][0]], 
                           [node1["pos"][1], node2["pos"][1]], 
                           color='lightgray', zorder=1)

        # Draw nodes
        for node_id, node in self.nodes.items():
            if node["status"] != "Active":
                node_color = 'gray'
            else:
                node_color = 'r' if node["is_master"] else 'g'
            
            circle = plt.Circle(node["pos"], 0.2, color=node_color, 
                              ec='black', zorder=2)
            self.ax.add_artist(circle)
            
            status_text = "Master" if node["is_master"] else "Node"
            if node["status"] != "Active":
                status_text = "Inactive"
                
            self.ax.annotate(f'Port {node["port"]}\n({status_text})',
                           xy=node["pos"], xytext=(0, 0),
                           textcoords='offset points',
                           ha='center', va='center',
                           color='black', zorder=3)

        self.ax.set_xlabel('X-axis')
        self.ax.set_ylabel('Y-axis')
        self._create_legend()
        self.figure.canvas.draw()

class NetworkMonitorThread(QThread):
    message_received = pyqtSignal(str)
    node_status_changed = pyqtSignal(int, str)
    node_added = pyqtSignal(int, str)
    master_changed = pyqtSignal(int)

    def __init__(self, host='localhost', port=5567, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.is_running = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((host, port))

    def run(self):
        self.is_running = True
        while self.is_running:
            try:
                data, addr = self.socket.recvfrom(4096)
                message = json.loads(data.decode())
                self.process_message(message)
            except Exception as e:
                print(f"Error receiving message: {e}")

    def process_message(self, message):
        msg_type = message['type']
        data = message['data']

        if msg_type == 'LOG':
            self.message_received.emit(data['message'])
        elif msg_type == 'NODE_ADDED':
            self.node_added.emit(data['port'], data['node_type'])
        elif msg_type == 'NODE_STATUS':
            self.node_status_changed.emit(data['node_id'], data['status'])
        elif msg_type == 'MASTER_CHANGED':
            self.master_changed.emit(data['master_id'])

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
    def __init__(self, host='localhost', port=5567):
        super().__init__()
        self.setWindowTitle("Network Monitor")
        self.setMinimumSize(800, 500)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)

        # Create left panel for event log
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        layout.addWidget(left_panel)

        # Add event log to left panel
        log_label = QLabel("Event Log")
        log_label.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            padding: 5px;
            background-color: #fcba03;
            border-radius: 5px;
        """)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumWidth(250)
        left_layout.addWidget(log_label)
        left_layout.addWidget(self.log_text)

        # Create network visualizer
        self.network_viz = NetworkVisualizerWidget()
        layout.addWidget(self.network_viz)

        # Start monitor thread
        self.monitor_thread = NetworkMonitorThread(host, port)
        self.monitor_thread.message_received.connect(self.log_message)
        self.monitor_thread.node_status_changed.connect(self.network_viz.updateNodeStatus)
        self.monitor_thread.node_added.connect(self.network_viz.addNode)
        self.monitor_thread.master_changed.connect(self.network_viz.updateMasterStatus)
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
    window = MonitorGUI()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()