import os
import cmd
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
            # logger.info("Status tracking started")

    def stop_status_tracking(self):
        """Stop the status tracking thread"""
        self.tracking = False
        if self.tracker_thread:
            self.tracker_thread.join()
            # logger.info("Status tracking stopped")

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
                        '''
                        logger.info(f"HEARTBEAT - Armed: {self.current_status['armed']}, "
                                  f"Status: {self.current_status['system_status']}")
                        '''
                    elif msg_type == 'GLOBAL_POSITION_INT':
                        self.current_status['altitude'] = msg.relative_alt / 1000  # Convert to meters
                        self.current_status['position'] = (msg.lat / 1e7, msg.lon / 1e7)  # Convert to degrees
                        '''
                        logger.info(f"POSITION - Alt: {self.current_status['altitude']:.1f}m, "
                                  f"Lat: {self.current_status['position'][0]:.6f}, "
                                  f"Lon: {self.current_status['position'][1]:.6f}")
                        '''

                    elif msg_type == 'VFR_HUD':
                        self.current_status['groundspeed'] = msg.groundspeed
                        self.current_status['heading'] = msg.heading
                        '''
                        logger.info(f"VFR - Speed: {msg.groundspeed:.1f}m/s, "
                                  f"Heading: {msg.heading}°")
                        '''

                    elif msg_type == 'GPS_RAW_INT':
                        self.current_status['gps'] = {
                            'fix_type': msg.fix_type,
                            'satellites_visible': msg.satellites_visible
                        }
                        '''
                        logger.info(f"GPS - Fix: {msg.fix_type}, "
                                  f"Satellites: {msg.satellites_visible}")
                        '''

                    elif msg_type == 'SYS_STATUS':
                        battery_remaining = msg.battery_remaining if hasattr(msg, 'battery_remaining') else None
                        voltage = msg.voltage_battery if hasattr(msg, 'voltage_battery') else None
                        self.current_status['battery'] = {
                            'percentage': battery_remaining,
                            'voltage': voltage
                        }
                        if voltage:
                            '''
                            logger.info(f"BATTERY - Remaining: {battery_remaining}%, "
                                      f"Voltage: {voltage/1000:.2f}V")
                        else:
                            logger.info("BATTERY - Data not available")
                            '''

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

    def get_current_mode(self):
        """
        Get the current flight mode of the drone

        Returns:
            str: Current flight mode, or None if not connected
        """
        if not self.drone:
            return None

        try:
            # Request flight mode information from the drone
            self.drone.mav.command_long_send(
                self.drone.target_system,
                self.drone.target_component,
                mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                0,  # Confirmation
                mavutil.mavlink.MAVLINK_MSG_ID_HEARTBEAT,  # Message ID for heartbeat that contains mode info
                0, 0, 0, 0, 0, 0  # Unused parameters
            )

            # Wait for heartbeat message to get mode
            msg = self.drone.recv_match(type='HEARTBEAT', blocking=True, timeout=1.0)
            if msg:
                # Convert mode to string using MAVLink mode mapping
                custom_mode = msg.custom_mode
                flight_mode = mavutil.mode_mapping_acm.get(custom_mode)

                # Update internal mode tracking
                self.flight_mode = flight_mode
                logger.info(f"Current flight mode: {flight_mode}")
                return flight_mode
            else:
                logger.warning("Couldn't retrieve flight mode - no heartbeat received")
                return self.flight_mode  # Return last known mode if available

        except Exception as e:
            logger.error(f"Error getting flight mode: {str(e)}")
            return self.flight_mode  # Return last known mode on error

    def get_drone_status(self):
        """
        Get comprehensive drone status information

        Returns:
            dict: Dictionary containing current drone status values
        """
        if not self.drone:
            return {
                'connected': False
            }

        # Get current mode if we don't have it
        if not self.flight_mode:
            self.get_current_mode()

        # Compile status information
        status = {
            'connected': True,
            'armed': self.is_armed,
            'mode': self.flight_mode,
            'altitude': self.altitude,
        }

        # Add extended status if available
        if hasattr(self, 'current_status'):
            for key, value in self.current_status.items():
                status[key] = value

        return status

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


class DroneShell(cmd.Cmd):
    intro = 'Welcome to the drone control shell. Type help or ? to list commands.\n'
    prompt = '(drone) '

    def __init__(self):
        super().__init__()
        self.drone_controller = None

    def do_connect(self, arg):
        """
        Connect to the drone.
        Usage: connect [connection_string]
        Default connection: udp:127.0.0.1:14550
        """
        connection_string = arg if arg else "udp:127.0.0.1:14550"
        self.drone_controller = DroneController(connection_string)
        if self.drone_controller.connect():
            print(f"Successfully connected to {connection_string}")
        else:
            print("Failed to connect")
            self.drone_controller = None

    def do_arm(self, arg):
        """Arm the drone"""
        if self._check_connection():
            if self.drone_controller.arm():
                print("Drone armed successfully")

    def do_disarm(self, arg):
        """Disarm the drone"""
        if self._check_connection():
            self.drone_controller.disarm()

    def do_mode(self, arg):
        """
        Set flight mode
        Usage: mode <mode_name>
        Example: mode GUIDED
        """
        if not arg:
            print("Error: Please specify a flight mode")
            return
        if self._check_connection():
            self.drone_controller.set_flight_mode(arg)

    def do_takeoff(self, arg):
        """
        Take off to specified altitude
        Usage: takeoff <altitude>
        Example: takeoff 10
        """
        try:
            altitude = float(arg)
            if self._check_connection():
                if self.drone_controller.arm():  # Ensure drone is armed
                    time.sleep(1)
                    self.drone_controller.takeoff(altitude)
        except ValueError:
            print("Error: Please provide a valid altitude in meters")

    def do_throttle(self, arg):
        """
        Set throttle value (0-100)
        Usage: throttle <value>
        Example: throttle 50
        """
        try:
            value = int(arg)
            if self._check_connection():
                self.drone_controller.set_throttle(value)
        except ValueError:
            print("Error: Please provide a valid throttle value (0-100)")

    def do_status(self, arg):
        """
        Show current drone status
        Usage: status [duration]
        Example: status 5 (shows status for 3 seconds)
        """
        if not self._check_connection():
            return

        timeout = 3
        start_time = time.time()
        while time.time() - start_time < timeout:
            print(f"position: {self.drone_controller.current_status['position']}")
            time.sleep(1)

        print("status monitoring ended")

    def do_quit(self, arg):
        """Quit the drone control shell"""
        if self.drone_controller:
            self.drone_controller.cleanup()
        print("\nGoodbye!")
        return True

    def _check_connection(self):
        """Check if drone is connected"""
        if not self.drone_controller:
            print("Error: Not connected to drone. Use 'connect' first.")
            return False
        return True

    # Shortcuts for common commands
    do_q = do_quit
    do_exit = do_quit

def main():
    try:
        DroneShell().cmdloop()
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        if DroneShell().drone_controller:
            DroneShell().drone_controller.cleanup()



if __name__ == "__main__":
    main()
