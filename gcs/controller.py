import os
import sys
import argparse
import time
import threading
from pymavlink import mavutil
from datetime import datetime
from loguru import logger 

# Configure loguru logger for console output only
logger.remove()  # Remove default sink
logger.add(
    sink=sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    colorize=True,
    level="INFO"
)

'''
# Remove default console logger
logger.remove()
# Configure loguru to only log to file
logger.add(
    "drone_controller.log",
    # sink=sys.stderr,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
    rotation="10 MB",
    retention="7 days",
    compression="zip",
    level="INFO",
    backtrace=True,
    diagnose=True
)
'''

class DroneController:
    def __init__(self, connection_string="udp:127.0.0.1:14550"):
        """
        Initialize drone controller with connection string
        Args:
            connection_string (str): MAVLink connection string
        """
        self.connection_string = connection_string
        self.drone = None
        self.is_armed = False
        self.flight_mode = None
        self.altitude = 0

        # Status tracking variables
        self.current_status = {
            'armed': False,
            'mode': None,
            'altitude': 0,
            'battery': None,
            'gps': None,
            'heading': None,
            'groundspeed': None,
            'position': None,
            'system_status': None
        }
        self.tracking = False
        self.tracker_thread = None

    def start_status_tracking(self):
        """Start the background status tracking thread"""
        if not self.tracking:
            self.tracking = True
            self.tracker_thread = threading.Thread(target=self._status_tracker)
            self.tracker_thread.daemon = True  # Thread will close when main program exits
            self.tracker_thread.start()
            logger.info("Status tracking started")

    def stop_status_tracking(self):
        """Stop the status tracking thread"""
        self.tracking = False
        if self.tracker_thread:
            self.tracker_thread.join()
            logger.info("Status tracking stopped")

    def _status_tracker(self):
        """Background thread function to track drone status"""
        while self.tracking and self.drone:
            try:
                # Receive messages
                msg = self.drone.recv_match(blocking=True, timeout=1.0)
                if msg:
                    msg_type = msg.get_type()
                    timestamp = datetime.now().strftime("%H:%M:%S")

                    # Process different message types
                    if msg_type == 'HEARTBEAT':
                        self.current_status['armed'] = msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                        self.current_status['system_status'] = mavutil.mavlink.enums['MAV_STATE'][msg.system_status].name
                        logger.info(f"HEARTBEAT - Armed: {self.current_status['armed']}, "
                                  f"Status: {self.current_status['system_status']}")

                    elif msg_type == 'GLOBAL_POSITION_INT':
                        self.current_status['altitude'] = msg.relative_alt / 1000  # Convert to meters
                        self.current_status['position'] = (msg.lat / 1e7, msg.lon / 1e7)  # Convert to degrees
                        logger.info(f"POSITION - Alt: {self.current_status['altitude']:.1f}m, "
                                  f"Lat: {self.current_status['position'][0]:.6f}, "
                                  f"Lon: {self.current_status['position'][1]:.6f}")

                    elif msg_type == 'VFR_HUD':
                        self.current_status['groundspeed'] = msg.groundspeed
                        self.current_status['heading'] = msg.heading
                        logger.info(f"VFR - Speed: {msg.groundspeed:.1f}m/s, "
                                  f"Heading: {msg.heading}°")

                    elif msg_type == 'GPS_RAW_INT':
                        self.current_status['gps'] = {
                            'fix_type': msg.fix_type,
                            'satellites_visible': msg.satellites_visible
                        }
                        logger.info(f"GPS - Fix: {msg.fix_type}, "
                                  f"Satellites: {msg.satellites_visible}")

                    elif msg_type == 'SYS_STATUS':
                        battery_remaining = msg.battery_remaining if hasattr(msg, 'battery_remaining') else None
                        voltage = msg.voltage_battery if hasattr(msg, 'voltage_battery') else None
                        self.current_status['battery'] = {
                            'percentage': battery_remaining,
                            'voltage': voltage
                        }
                        if voltage:
                            logger.info(f"BATTERY - Remaining: {battery_remaining}%, "
                                      f"Voltage: {voltage/1000:.2f}V")
                        else:
                            logger.info("BATTERY - Data not available")

            except Exception as e:
                logger.error(f"Error in status tracker: {str(e)}")
                time.sleep(1)  # Prevent tight loop in case of errors

    def connect(self):
        """
        Establish connection with the drone
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.drone = mavutil.mavlink_connection(self.connection_string)
            self.drone.wait_heartbeat()
            logger.success(f"Connected to drone! (system: {self.drone.target_system}, "
                         f"component: {self.drone.target_component})")

            # Start status tracking after connection
            self.start_status_tracking()
            return True
        except Exception as e:
            logger.error(f"Connection failed: {str(e)}")
            return False

    def arm(self):
        """
        Arm the drone
        Returns:
            bool: True if arming successful, False otherwise
        """
        if not self.drone:
            logger.error("No drone connection")
            return False

        # Set mode to GUIDED
        self.set_flight_mode("GUIDED")
        time.sleep(1)  # Wait for mode change

        # Send arm command
        self.drone.mav.command_long_send(
            self.drone.target_system,
            self.drone.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1, 0, 0, 0, 0, 0, 0
        )

        # Wait for arm acknowledge
        ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
        if ack and ack.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            self.is_armed = (ack.result == 0)
            if self.is_armed:
                logger.success("Armed successfully!")
            else:
                logger.error("Arming failed!")
            return self.is_armed
        return False

    def disarm(self):
        """
        Disarm the drone
        Returns:
            bool: True if disarming successful, False otherwise
        """
        if not self.drone:
            logger.error("No drone connection")
            return False

        self.drone.mav.command_long_send(
            self.drone.target_system,
            self.drone.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0, 0, 0, 0, 0, 0, 0
        )

        ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
        if ack and ack.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            self.is_armed = not (ack.result == 0)
            if not self.is_armed:
                logger.success("Disarmed successfully!")
            else:
                logger.error("Disarming failed!")
            return not self.is_armed
        return False

    def takeoff(self, target_altitude):
        """
        Take off to specified altitude
        Args:
            target_altitude (float): Target altitude in meters
        Returns:
            bool: True if takeoff command accepted, False otherwise
        """
        if not self.drone or not self.is_armed:
            logger.error("Drone not connected or not armed")
            return False

        self.drone.mav.command_long_send(
            self.drone.target_system,
            self.drone.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0, 0, 0, 0, 0, 0,
            target_altitude
        )

        ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
        if ack and ack.command == mavutil.mavlink.MAV_CMD_NAV_TAKEOFF:
            success = (ack.result == 0)
            if success:
                logger.success(f"Takeoff command accepted! Target altitude: {target_altitude}m")
                self.altitude = target_altitude
            else:
                logger.error("Takeoff command failed!")
            return success
        return False

    def set_flight_mode(self, mode):
        """
        Set the flight mode of the drone
        Args:
            mode (str): Flight mode to set
        Returns:
            bool: True if mode change successful, False otherwise
        """
        if not self.drone:
            logger.error("No drone connection")
            return False

        try:
            self.drone.set_mode(mode)
            self.flight_mode = mode
            logger.success(f"Flight mode set to {mode}")
            return True
        except Exception as e:
            logger.error(f"Failed to set flight mode: {str(e)}")
            return False

    def set_throttle(self, throttle_value):
        """
        Set the throttle value
        Args:
            throttle_value (int): Throttle percentage (0-100)
        Returns:
            bool: True if throttle set successfully, False otherwise
        """
        if not self.drone or not self.is_armed:
            logger.error("Drone not connected or not armed")
            return False

        if 0 <= throttle_value <= 100:
            pwm = 1000 + (throttle_value * 10)
            self.drone.mav.rc_channels_override_send(
                self.drone.target_system,
                self.drone.target_component,
                pwm,    # Throttle channel
                65535, 65535, 65535,  # Other channels (unused)
                65535, 65535, 65535, 65535
            )
            logger.success(f"Throttle set to {throttle_value}%")
            return True
        else:
            logger.error("Invalid throttle value (0-100)")
            return False

    def cleanup(self):
        """
        Cleanup method to be called before program exit
        """
        self.stop_status_tracking()
        if self.drone:
            self.drone.close()
            logger.info("Drone connection closed")


def create_parser():
    """Create argument parser for drone commands"""
    parser = argparse.ArgumentParser(description='Drone Control CLI')
    
    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Connect command
    connect_parser = subparsers.add_parser('connect', help='Connect to drone')
    connect_parser.add_argument('--connection', type=str, default="udp:127.0.0.1:14550",
                              help='Connection string (default: udp:127.0.0.1:14550)')
    
    # Arm command
    arm_parser = subparsers.add_parser('arm', help='Arm the drone')
    
    # Disarm command
    disarm_parser = subparsers.add_parser('disarm', help='Disarm the drone')
    
    # Mode command
    mode_parser = subparsers.add_parser('mode', help='Set flight mode')
    mode_parser.add_argument('mode_name', type=str, help='Flight mode to set (e.g., GUIDED, AUTO, RTL)')
    
    # Takeoff command
    takeoff_parser = subparsers.add_parser('takeoff', help='Take off to specified altitude')
    takeoff_parser.add_argument('altitude', type=float, help='Target altitude in meters')
    
    # Throttle command
    throttle_parser = subparsers.add_parser('throttle', help='Set throttle value')
    throttle_parser.add_argument('value', type=int, help='Throttle value (0-100)')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show drone status')
    status_parser.add_argument('--duration', type=int, default=10,
                             help='Duration to show status in seconds (default: 10)')
    
    return parser


# Example usage
def main():
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Create drone controller instance
    drone = None
    
    try:
        if args.command == 'connect':
            drone = DroneController(args.connection)
            if drone.connect():
                print(f"Successfully connected to {args.connection}")
                # Keep connection alive for a moment to see initial status
                time.sleep(3)
            else:
                print("Failed to connect")
                return
        
        elif args.command in ['arm', 'disarm', 'mode', 'takeoff', 'throttle', 'status']:
            # For all other commands, first establish connection with default settings
            drone = DroneController()
            if not drone.connect():
                print("Failed to connect to drone")
                return
            
            # Process specific commands
            if args.command == 'arm':
                if drone.arm():
                    print("Drone armed successfully")
                    time.sleep(3)  # Wait to see status update
                
            elif args.command == 'disarm':
                if drone.disarm():
                    print("Drone disarmed successfully")
                    time.sleep(3)
                
            elif args.command == 'mode':
                if drone.set_flight_mode(args.mode_name):
                    print(f"Flight mode set to {args.mode_name}")
                    time.sleep(3)
                
            elif args.command == 'takeoff':
                if drone.arm():  # Make sure drone is armed before takeoff
                    time.sleep(2)
                    if drone.takeoff(args.altitude):
                        print(f"Taking off to {args.altitude}m")
                        time.sleep(10)  # Wait to see takeoff progress
                
            elif args.command == 'throttle':
                if drone.set_throttle(args.value):
                    print(f"Throttle set to {args.value}%")
                    time.sleep(3)
                
            elif args.command == 'status':
                print(f"Monitoring drone status for {args.duration} seconds...")
                time.sleep(args.duration)
    
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
    finally:
        if drone:
            drone.cleanup()


if __name__ == "__main__":
    main()
