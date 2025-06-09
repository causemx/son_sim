# Drone Network Control System

This project implements a distributed drone control network system with automatic connection management, node status reporting, and a visualization GUI. The system consists of three main components: nodes, a central handler, and a GUI interface.

## System Architecture

- **Nodes**: Individual computers that control drones
- **Handler**: Central coordinator that manages the network
- **GUI**: Visual interface for monitoring and controlling the network

## Getting Started

### Prerequisites

- Python 3.6+
- PyQt5
- pymavlink
- folium
- PyQtWebEngine

### Installation

1. Clone the repository:
   ```bash
   git clone http://140.96.186.124:3000/causemx/son_sim.git
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the System

### 1. Start the Handler

Make sure handler, nodes in same mesh, handler and gui in same DNS.
The handler is the central coordinator for the network:

```bash
python handler.py
```

The handler will start and (group, id) will be (1, 11).


### 2. Start the GUI

The GUI provides visual monitoring and control and (group, id) was (1, 1):

```bash
python gui.py
```

### 3. Start Nodes

Start one or more nodes, specifying their node id:

```bash
python node.py 12
python node.py 13
# Add more nodes as needed
```

Each node will attempt to automatically connect to its drone. If successful, it will register with the handler.


## Handler Commands

The handler provides a command-line interface for controlling drones:

### Network Commands

- `nodes` - List all connected nodes
- `detailed_status <node_id|all>` - Show detailed status for node(s)

### Drone Connection Commands

- `connect <node_id|all>` - Connect to drone(s)
- `status <node_id|all>` - Get drone status

### Flight Control Commands

- `arm <node_id|all>` - Arm the drone
- `disarm <node_id|all>` - Disarm the drone
- `mode <mode_name> <node_id|all>` - Set flight mode (e.g., `mode GUIDED 1`)
- `getmode <node_id|all>` - Get current flight mode
- `takeoff <altitude> <node_id|all>` - Take off to specified altitude (e.g., `takeoff 10 1`)
- `throttle <value> <node_id|all>` - Set throttle value (0-100)
- `stop <node_id|all>` - Execute emergency stop

## System Behavior

### Node Auto-Connect

Nodes will attempt to connect to their drones automatically on startup:

1. When a node starts, it tries to connect to its drone (up to 5 attempts)
2. If connection succeeds, it registers with the handler and starts sending status updates
3. If connection fails, the node will not register with the handler

### Manual Connection

If auto-connect fails, you can manually connect a node using the handler:

```bash
connect 12  # Connect node with ID 1
```

Once connected, the node will register with the handler and start sending status updates.

### Status Reporting

Connected nodes continuously report their status to the handler, including:
- Armed state
- Flight mode
- Position
- Altitude
- GPS information
- Heading
- Groundspeed
- System status

### Master Node Selection

The system automatically selects a master node which has special coordination responsibilities.

## GUI Features

The GUI visualizes the network in real-time:

- Network topology with node connections
- Node status indicators 
- Master node highlighting
- Detailed drone information on marker click
- Event log displaying system activities
- Node status panel showing connected drones

## Notes and Troubleshooting

- If a node appears unresponsive, check its terminal output for error messages
- Nodes only register with the handler after successfully connecting to a drone
- If a drone shows position [0.0, 0.0], the system will simulate a position automatically
- The default geographic area for visualization is centered at [24.7739578, 121.0455114]

## Project Files

- `node_base.py` - Base class for nodes with drone control
- `node.py` - Node executable script
- `handler.py` - Network handler and command shell
- `controller.py` - Drone controller using pymavlink
- `drone_v2x.py` - DSRC module driver for communication(it's suck)
- `gui.py` - Network visualization interface

## Emergency Procedures

In case of emergency, you can stop all drones using:

```bash
stop all
```

This sets all drones to BRAKE mode and attempts to disarm them if possible.
