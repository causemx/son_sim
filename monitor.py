from node_base import Node, NodeType
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QPushButton, QTextEdit)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import sys
import time
import math

class NetworkVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.nodes = {}
        self.last_heartbeat = {}
        self.center_x = 0  # Will use normalized coordinates
        self.center_y = 0
        self.radius = 0.8  # Use normalized radius
        
        # Create the figure and canvas
        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        
        # Set up the layout
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Configure plot
        self.ax.set_xlim(-1.2, 1.2)
        self.ax.set_ylim(-1.2, 1.2)
        self.ax.set_aspect('equal')
        self.ax.axis('off')

    def addNode(self, port, node_type):
        node_id = port % 1000
        if node_type == "MONITOR":
            return
            
        num_nodes = len([n for n in self.nodes.values() if n["type"] != "MONITOR"])
        angle = (num_nodes * 2 * math.pi) / 3
        x = self.center_x + self.radius * math.cos(angle)
        y = self.center_y + self.radius * math.sin(angle)
        pos = (x, y)

        self.nodes[node_id] = {
            "pos": pos,
            "type": node_type,
            "status": "Active",
            "color": 'g',  # Default green for nodes
            "port": port,
            "is_master": False,
            "last_seen": time.time()
        }
        self._redraw()

    def updateMasterStatus(self, master_id):
        for node in self.nodes.values():
            if node["status"] == "Active":
                node["is_master"] = False
                node["color"] = 'g'  # Green for regular nodes

        if master_id in self.nodes and self.nodes[master_id]["status"] == "Active":
            self.nodes[master_id]["is_master"] = True
            self.nodes[master_id]["color"] = 'r'  # Red for master
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

    def checkNodeStatus(self):
        current_time = time.time()
        for node_id, node in self.nodes.items():
            if node["status"] == "Active" and current_time - node["last_seen"] > 3:
                self.updateNodeStatus(node_id, "Inactive")

    def _redraw(self):
        self.ax.clear()
        self.ax.set_xlim(-1.2, 1.2)
        self.ax.set_ylim(-1.2, 1.2)
        self.ax.set_aspect('equal')
        self.ax.axis('off')

        # Draw connections between active nodes
        active_nodes = [(nid, node) for nid, node in self.nodes.items() 
                       if node["status"] == "Active"]
        
        for i in range(len(active_nodes)):
            for j in range(i + 1, len(active_nodes)):
                node1 = active_nodes[i][1]
                node2 = active_nodes[j][1]
                self.ax.plot([node1["pos"][0], node2["pos"][0]], 
                           [node1["pos"][1], node2["pos"][1]], 
                           color='lightgray', zorder=1)

        # Draw nodes
        for node_id, node in self.nodes.items():
            # Draw node circle
            circle = plt.Circle(node["pos"], 0.15, color=node["color"], 
                              ec='black', zorder=2)
            self.ax.add_artist(circle)
            
            # Add node labels
            status_text = "Master" if node["is_master"] else "Node"
            if node["status"] != "Active":
                status_text = "Inactive"
                
            self.ax.annotate(f'Port {node["port"]}\n({status_text})',
                           xy=node["pos"], xytext=(0, 0),
                           textcoords='offset points',
                           ha='center', va='center',
                           color='black', zorder=3)

        self.figure.canvas.draw()

class MonitorThread(QThread):
    message_received = pyqtSignal(str)
    node_status_changed = pyqtSignal(int, str)
    node_added = pyqtSignal(int, str)
    master_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.monitor_node = None
        self.is_running = False
        self.known_nodes = set()

    def run(self):
        # Create monitor node
        self.monitor_node = Node(5000, NodeType.MONITOR)
        self.node_added.emit(5000, "MONITOR")
        self.known_nodes.add(0)  # Add monitor's node_id (5000 % 1000 = 0)

        def new_process_message(message):
            msg_type = message['type']
            from_node = message['from']
            
            # Add new node when first message is received
            if from_node not in self.known_nodes:
                self.node_added.emit(5000 + from_node, "NODE")
                self.known_nodes.add(from_node)
                self.message_received.emit(f"Node {from_node} (Port {5000 + from_node}) joined network")
            
            if msg_type == 'HEARTBEAT':
                self.master_changed.emit(from_node)
            elif msg_type == 'ELECTION':
                self.message_received.emit(f"Election process started")
            elif msg_type == 'NEW_MASTER':
                new_master = message['data']['master_id']
                self.message_received.emit(f"Node {new_master} became master")
                self.master_changed.emit(new_master)

        # Override message processing
        self.monitor_node._process_message = new_process_message
        self.monitor_node.start()
        self.is_running = True

        while self.is_running:
            time.sleep(1)
            current_time = time.time()
            for node_id in self.known_nodes:
                if node_id != 0:  # Skip monitor node
                    if node_id in self.monitor_node.last_heartbeat:
                        if current_time - self.monitor_node.last_heartbeat[node_id] > 3:
                            self.node_status_changed.emit(node_id, "Inactive")
                            self.message_received.emit(f"Node {node_id} became inactive")
                        elif self.monitor_node.nodes.get(node_id, {}).get("status") == "Inactive":
                            self.node_status_changed.emit(node_id, "Active")
                            self.message_received.emit(f"Node {node_id} became active")

    def stop(self):
        self.is_running = False
        if self.monitor_node:
            self.monitor_node.stop()

class MonitorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Monitor")
        self.setMinimumSize(800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)

        # Create network visualizer
        self.network_viz = NetworkVisualizerWidget()
        layout.addWidget(self.network_viz)

        # Create right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        layout.addWidget(right_panel)

        # Add event log
        log_label = QLabel("Event Log:")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        right_layout.addWidget(log_label)
        right_layout.addWidget(self.log_text)

        # Start monitor thread
        self.monitor_thread = MonitorThread()
        self.monitor_thread.message_received.connect(self.log_message)
        self.monitor_thread.node_status_changed.connect(self.network_viz.updateNodeStatus)
        self.monitor_thread.node_added.connect(self.network_viz.addNode)
        self.monitor_thread.master_changed.connect(self.network_viz.updateMasterStatus)
        self.monitor_thread.start()

    def log_message(self, message):
        self.log_text.append(message)

    def closeEvent(self, event):
        self.monitor_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MonitorGUI()
    window.show()
    sys.exit(app.exec_())