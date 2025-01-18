import socket
import time
import math
import random
import sys
import struct

class PositionSimulator:
    def __init__(self, node_ids=[1, 2, 3]):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.node_ids = node_ids
        self.node_positions = {}
        
        # Initialize positions for each node with random positions in 0-5 range
        for node_id in node_ids:
            self.node_positions[node_id] = {
                'x': random.uniform(1.0, 4.0),  # Keep away from borders
                'y': random.uniform(1.0, 4.0),
                'z': random.uniform(0.0, 1.0),  # Z height
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
            center_x = 2.5 + random.uniform(-0.05, 0.05)  # Center of the area
            center_y = 2.5 + random.uniform(-0.05, 0.05)
            radius = 1.5 + random.uniform(-0.25, 0.25)    # Orbit radius
            
            # Update x and y positions
            pos['x'] = center_x + radius * math.cos(pos['angle'])
            pos['y'] = center_y + radius * math.sin(pos['angle'])
            
            # Add small random movement to z
            pos['z'] += random.uniform(-0.05, 0.05)
            
            # Ensure positions stay within bounds
            pos['x'] = max(0.5, min(4.5, pos['x']))  # Keep away from borders
            pos['y'] = max(0.5, min(4.5, pos['y']))
            pos['z'] = max(0.0, min(1.5, pos['z']))

    def send_positions(self):
        """Send current positions via UDP using struct packing"""
        for node_id in self.node_ids:
            pos = self.node_positions[node_id]
            
            # Pack data as: node_id (float), x (float), y (float), z (float)
            packed_data = struct.pack("ffff", 
                float(node_id),
                pos['x'],
                pos['y'],
                pos['z']
            )
            
            self.socket.sendto(packed_data, ('localhost', 17500))
            print(f"Sent position update for Node {node_id}: x={pos['x']:.3f}, y={pos['y']:.3f}, z={pos['z']:.3f}")

    def run(self, update_interval=3):
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
        node_ids = range(1, 11)

    # Create and run simulator
    simulator = PositionSimulator(node_ids)
    simulator.run()

if __name__ == "__main__":
    main()