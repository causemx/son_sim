import socket
import time
import sys
import struct

class PositionSimulator:
    def __init__(self, node_ids=[1, 2, 3]):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.node_ids = node_ids
        self.node_positions = {}
        
        # Calculate number of rows needed for inverted triangle
        total_nodes = len(node_ids)
        
        # Initialize fixed positions for inverted triangle formation
        node_index = 0
        current_row = 0
        base_y = 4.0  # Starting y position (top of triangle)
        
        while node_index < total_nodes:
            # Calculate number of nodes in current row
            nodes_in_row = current_row + 1
            
            # Calculate starting x position for current row to center it
            base_x = 2.5 - (nodes_in_row - 1) * 0.5
            
            # Place nodes in current row
            for i in range(nodes_in_row):
                if node_index < total_nodes:
                    node_id = node_ids[node_index]
                    self.node_positions[node_id] = {
                        'x': base_x + i,  # Horizontal spacing of 1.0
                        'y': base_y - current_row,  # Vertical spacing of 1.0
                        'z': 0.5  # Fixed height
                    }
                    node_index += 1
            
            current_row += 1

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

    def run(self, update_interval=2):
        """Run the simulation with specified update interval"""
        print(f"Starting fixed position simulation for nodes: {self.node_ids}")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
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
        # Default to nodes 1 through 10
        node_ids = list(range(1, 11))

    # Create and run simulator
    simulator = PositionSimulator(node_ids)
    simulator.run()

if __name__ == "__main__":
    main()