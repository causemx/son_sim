import json
import socket
import struct
import threading
from node_base import Node, NodeType
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QTextEdit)
from PyQt5.QtCore import pyqtSignal, QThread
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import sys
import time
import math

class NetworkVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.nodes = {}
        self.last_heartbeat = {}
        self.center_x = 2.5  # New center point
        self.center_y = 2.5  # New center point
        self.radius = 1.5    # Adjusted radius for new coordinate system
        
        # Create the figure and canvas
        self.figure = Figure(figsize=(6, 4))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        
        # Set up the layout
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Configure plot with new coordinate system
        self.ax.set_xlim(0, 5)
        self.ax.set_ylim(0, 5)
        self.ax.set_aspect('equal')
        self.ax.axis('on')  # Show axes
        self.ax.grid(True)  # Add grid
        
        # Add legend
        self._create_legend()

    def _create_legend(self):
        # Create legend patches
        master_patch = mpatches.Patch(color='r', label='Master Node')
        active_patch = mpatches.Patch(color='g', label='Active Node')
        inactive_patch = mpatches.Patch(color='gray', label='Inactive Node')
        
        # Add legend to the plot
        self.ax.legend(handles=[master_patch, active_patch, inactive_patch],
                      loc='upper right', bbox_to_anchor=(1.1, 1.1))

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
            "color": 'g',
            "port": port,
            "is_master": False,
            "last_seen": time.time()
        }
        self._redraw()

    def updateMasterStatus(self, master_id):
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
        
        for i in range(len(active_nodes)):
            for j in range(i + 1, len(active_nodes)):
                node1 = active_nodes[i][1]
                node2 = active_nodes[j][1]
                self.ax.plot([node1["pos"][0], node2["pos"][0]], 
                           [node1["pos"][1], node2["pos"][1]], 
                           color='lightgray', zorder=1)

        # Draw nodes
        for node_id, node in self.nodes.items():
            # Set color based on status
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
                print(f"Drawing inactive node {node_id} with gray color")  # Debug log
                
            self.ax.annotate(f'Port {node["port"]}\n({status_text})',
                           xy=node["pos"], xytext=(0, 0),
                           textcoords='offset points',
                           ha='center', va='center',
                           color='black', zorder=3)

        # Add axis labels
        self.ax.set_xlabel('X-axis')
        self.ax.set_ylabel('Y-axis')
        
        # Recreate legend
        self._create_legend()
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
        self.known_nodes.add(0)

        def new_process_message(message):
            msg_type = message['type']
            from_node = message['from']
            
            if from_node not in self.known_nodes:
                self.node_added.emit(5000 + from_node, "NODE")
                self.known_nodes.add(from_node)
                self.message_received.emit(f"Node {from_node} (Port {5000 + from_node}) joined network")
            
            if msg_type == 'HEARTBEAT':
                self.master_changed.emit(from_node)
            elif msg_type == 'ELECTION':
                self.message_received.emit("Election process started")
            elif msg_type == 'NEW_MASTER':
                new_master = message['data']['master_id']
                self.message_received.emit(f"Node {new_master} became master")
                self.master_changed.emit(new_master)

        self.monitor_node._process_message = new_process_message
        self.monitor_node.start()
        self.is_running = True

        while self.is_running:
            time.sleep(1)
            current_time = time.time()
            for node_id in self.known_nodes:
                if node_id != 0:
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
        self.log_text.setMinimumWidth(250)  # Set minimum width for log panel
        left_layout.addWidget(log_label)
        left_layout.addWidget(self.log_text)

        # Create network visualizer (now on the right)
        self.network_viz = NetworkVisualizerWidget()
        layout.addWidget(self.network_viz)

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


class Message:
    def __init__(self, version=None, port=None, host_int=None, displayname="", namespaces=None):
        self.version = version
        self.port = port
        self.host_int = host_int
        self.displayname = displayname
        self.namespaces = namespaces

    def to_dict(self):
        """Convert the class instance to a dictionary representation"""
        return {
            "version": self.version,
            "port": self.port,
            "host_int": self.host_int,
            "displayname": self.displayname,
            "namespaces": self.namespaces
        }

    @classmethod
    def from_dict(cls, data):
        """Create a class instance from a dictionary"""
        return cls(
            version=data.get("version"),
            port=data.get("port"),
            host_int=data.get("host_int"),
            displayname=data.get("displayname"),
            namespaces=data.get("namespaces")
        )

def _createReceivingSocket(port):
    print("[*] start receving position data")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.bind(("", port))
    return s


def _handle_udp_messages():
    s = _createReceivingSocket(17500)
    while True:
        data = s.recv(1024).decode()
        #print(data)
        data = json.loads(data)
        income_data_t = Message.from_dict(data)
        number = income_data_t.host_int
        # Convert the number to bytes
        number_bytes =  number.to_bytes((number.bit_length() + 7) // 8, byteorder='big')
        unpacked_value = struct.unpack('ffff', number_bytes)
        print(unpacked_value)
        

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # receive udp incoming position
    threading.Thread(target=_handle_udp_messages, daemon=True).start()

    window = MonitorGUI()
    window.show()
    sys.exit(app.exec_())