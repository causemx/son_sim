import socket
import json
import time
import math
import random
import sys

class PositionSimulator:
    def __init__(self, node_ids=[1, 2, 3]):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.node_ids = node_ids
        self.node_positions = {}
        
        # Initialize positions for each node with random positions
        for node_id in node_ids:
            self.node_positions[node_id] = {
                'x': random.uniform(0.2, 0.8),
                'y': random.uniform(0.2, 0.8),
                'angle': random.uniform(0, 2 * math.pi),
                'speed': random.uniform(0.02, 0.05)
            }

    def update_positions(self):
        """Update positions using circular motion with random variations"""
        for node_id in self.node_ids:
            pos = self.node_positions[node_id]
            
            # Update angle and add some random movement
            pos['angle'] += pos['speed']
            if pos['angle'] > 2 * math.pi:
                pos['angle'] -= 2 * math.pi
                
            # Calculate new position with some random variation
            center_x = 0.5 + random.uniform(-0.01, 0.01)
            center_y = 0.5 + random.uniform(-0.01, 0.01)
            radius = 0.3 + random.uniform(-0.05, 0.05)
            
            # Update x and y positions
            pos['x'] = center_x + radius * math.cos(pos['angle'])
            pos['y'] = center_y + radius * math.sin(pos['angle'])
            
            # Ensure positions stay within bounds (0-1)
            pos['x'] = max(0.1, min(0.9, pos['x']))
            pos['y'] = max(0.1, min(0.9, pos['y']))

    def send_positions(self):
        """Send current positions via UDP"""
        for node_id in self.node_ids:
            pos = self.node_positions[node_id]
            message = {
                'id': node_id,
                'x': pos['x'],
                'y': pos['y']
            }
            data = json.dumps(message).encode()
            self.socket.sendto(data, ('localhost', 17500))
            print(f"Sent position update for Node {node_id}: x={pos['x']:.2f}, y={pos['y']:.2f}")

    def run(self, update_interval=0.5):
        """Run the simulation with specified update interval"""
        print(f"Starting position simulation for nodes: {self.node_ids}")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                self.update_positions()
                self.send_positions()
                time.sleep(update_interval)
        except KeyboardInterrupt:
            print("\nStopping simulation...")
        finally:
            self.socket.close()

def main():
    # Parse command line arguments for node IDs
    if len(sys.argv) > 1:
        try:
            node_ids = [int(arg) for arg in sys.argv[1:]]
        except ValueError:
            print("Error: Node IDs must be integers")
            sys.exit(1)
    else:
        # Default to nodes 1, 2, and 3
        node_ids = [1, 2, 3]

    # Create and run simulator
    simulator = PositionSimulator(node_ids)
    simulator.run()

if __name__ == "__main__":
    main()