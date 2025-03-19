import os
import cmd
import sys
import argparse
import time
import threading
import enum
from pymavlink import mavutil
import pymavlink.dialects.v20.all as dialect
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

# Define flight mode as enum class
class FlightMode(enum.Enum):
    STABILIZE = "STABILIZE"
    GUIDED = "GUIDED"
    AUTO = "AUTO"
    LOITER = "LOITER"
    RTL = "RTL"  # Return to Launch
    LAND = "LAND"
    BRAKE = "BRAKE"
    DRIFT = "DRIFT"
    SPORT = "SPORT"
    FLIP = "FLIP"
    AUTOTUNE = "AUTOTUNE"
    POSHOLD = "POSHOLD"
    THROW = "THROW"
    AVOID_ADSB = "AVOID_ADSB"
    GUIDED_NOGPS = "GUIDED_NOGPS"
    CIRCLE = "CIRCLE"

    @classmethod
    def from_string(cls, mode_str):
        """Convert string to FlightMode enum"""
        try:
            return cls(mode_str.upper())
        except ValueError:
            logger.warning(f"Unknown flight mode: {mode_str}")
            return None

    @classmethod
    def to_string(cls, mode_enum):
        """Convert FlightMode enum to string"""
        if isinstance(mode_enum, cls):
            return mode_enum.value
        return str(mode_enum)

    def __str__(self):
        """String representation for enum value"""
        return self.value

    def __repr__(self):
        """String representation for debugging"""
        return f"FlightMode.{self.name}"

    def to_json(self):
        """Return JSON serializable representation"""
        return self.value

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
        self.flight_mode = None  # Will store FlightMode enum
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

    def stop_status_tracking(self):
        """Stop the status tracking thread"""
        self.tracking = False
        if self.tracker_thread:
            self.tracker_thread.join()

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
                        self.current_status['armed'] = bool(msg.base_mode & dialect.MAV_MODE_FLAG_SAFETY_ARMED)
                        self.current_status['system_status'] = dialect.enums['MAV_STATE'][msg.system_status].name

                        # Update flight mode from heartbeat
                        custom_mode = msg.custom_mode
                        flight_mode_str = mavutil.mode_mapping_acm.get(custom_mode)
                        if flight_mode_str:
                            try:
                                self.flight_mode = FlightMode.from_string(flight_mode_str)
                                self.current_status['mode'] = flight_mode_str
                            except (ValueError, AttributeError):
                                # If not a known enum value, store the string directly
                                self.flight_mode = flight_mode_str
                                self.current_status['mode'] = flight_mode_str

                    elif msg_type == 'GLOBAL_POSITION_INT':
                        self.current_status['altitude'] = msg.relative_alt / 1000  # Convert to meters
                        self.current_status['position'] = (msg.lat / 1e7, msg.lon / 1e7)  # Convert to degrees

                    elif msg_type == 'VFR_HUD':
                        self.current_status['groundspeed'] = msg.groundspeed
                        self.current_status['heading'] = msg.heading

                    elif msg_type == 'GPS_RAW_INT':
                        self.current_status['gps'] = {
                            'fix_type': msg.fix_type,
                            'satellites_visible': msg.satellites_visible
                        }

                    elif msg_type == 'SYS_STATUS':
                        battery_remaining = msg.battery_remaining if hasattr(msg, 'battery_remaining') else None
                        voltage = msg.voltage_battery if hasattr(msg, 'voltage_battery') else None
                        self.current_status['battery'] = {
                            'percentage': battery_remaining,
                            'voltage': voltage
                        }

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
        Arm the drone with retry capability
        Args:
            max_retries (int): Maximum number of retry attempts
            retry_delay (float): Delay between retries in seconds
        Returns:
            bool: True if arming successful, False otherwise
        """
        if not self.drone:
            logger.error("No drone connection")
            return False

        # Set mode to GUIDED
        self.set_flight_mode(FlightMode.GUIDED)
        time.sleep(1)  # Wait for mode change

        # Create arm command message
        arm_message = dialect.MAVLink_command_long_message(
            target_system=self.drone.target_system,
            target_component=self.drone.target_component,
            command=dialect.MAV_CMD_COMPONENT_ARM_DISARM,
            confirmation=0,
            param1=1,  # 1 to arm
            param2=0,
            param3=0,
            param4=0,
            param5=0,
            param6=0,
            param7=0
        )

        # Send the arm message
        self.drone.mav.send(arm_message)
        logger.info("Arm the vehicle")

        # Wait for arm acknowledge
        ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=1.0)

        if ack and ack.command == dialect.MAV_CMD_COMPONENT_ARM_DISARM:
            success = (ack.result == dialect.MAV_RESULT_ACCEPTED)
            if success:
                self.is_armed = True
                logger.success("Armed successfully!")
                return True
            else:
                # Log the specific failure reason if available
                result_name = dialect.enums['MAV_RESULT'][ack.result].name if ack.result in dialect.enums['MAV_RESULT'] else f"Unknown ({ack.result})"
                logger.warning(f"Arm attempt failed: {result_name}")
        else:
            logger.warning("No acknowledgment received for arm attempt")


        return False

    def disarm(self, max_retries=3, retry_delay=2):
        """
        Disarm the drone with retry capability
        Args:
            max_retries (int): Maximum number of retry attempts
            retry_delay (float): Delay between retries in seconds
        Returns:
            bool: True if disarming successful, False otherwise
        """
        if not self.drone:
            logger.error("No drone connection")
            return False

        # Create disarm command message
        disarm_message = dialect.MAVLink_command_long_message(
            target_system=self.drone.target_system,
            target_component=self.drone.target_component,
            command=dialect.MAV_CMD_COMPONENT_ARM_DISARM,
            confirmation=0,
            param1=0,  # 0 to disarm
            param2=0,
            param3=0,
            param4=0,
            param5=0,
            param6=0,
            param7=0
        )

        # Try disarming with retries using while loop
        attempts = 0
        while attempts < max_retries:
            attempts += 1

            # Send the disarm message
            self.drone.mav.send(disarm_message)
            logger.info(f"Disarm attempt {attempts}/{max_retries}")

            # Wait for acknowledgment
            ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=1.0)

            if ack and ack.command == dialect.MAV_CMD_COMPONENT_ARM_DISARM:
                success = (ack.result == dialect.MAV_RESULT_ACCEPTED)
                if success:
                    self.is_armed = False
                    logger.success("Disarmed successfully!")
                    return True
                else:
                    # Log the specific failure reason if available
                    result_name = dialect.enums['MAV_RESULT'][ack.result].name if ack.result in dialect.enums['MAV_RESULT'] else f"Unknown ({ack.result})"
                    logger.warning(f"Disarm attempt {attempts} failed: {result_name}")
            else:
                logger.warning(f"No acknowledgment received for disarm attempt {attempts}")

            # Check if we should retry
            if attempts < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Disarming failed after {max_retries} attempts")

        return False

    def takeoff(self, target_altitude, max_retries=3, retry_delay=2):
        """
        Take off to specified altitude with retry capability
        Args:
            target_altitude (float): Target altitude in meters
            max_retries (int): Maximum number of retry attempts
            retry_delay (float): Delay between retries in seconds
        Returns:
            bool: True if takeoff command accepted, False otherwise
        """
        if not self.drone:
            logger.error("Drone not connected")
            return False

        # Create arm command message
        arm_message = dialect.MAVLink_command_long_message(
            target_system=self.drone.target_system,
            target_component=self.drone.target_component,
            command=dialect.MAV_CMD_COMPONENT_ARM_DISARM,
            confirmation=0,
            param1=1,  # 1 to arm
            param2=0,
            param3=0,
            param4=0,
            param5=0,
            param6=0,
            param7=0
        )

        # Send the arm message
        self.drone.mav.send(arm_message)
        logger.info("Arm the vehicle")
        time.sleep(1)

        # Create takeoff command message
        takeoff_message = dialect.MAVLink_command_long_message(
            target_system=self.drone.target_system,
            target_component=self.drone.target_component,
            command=dialect.MAV_CMD_NAV_TAKEOFF,
            confirmation=0,
            param1=0,
            param2=0,
            param3=0,
            param4=0,
            param5=0,
            param6=0,
            param7=target_altitude
        )

        # Try takeoff with retries using while loop
        attempts = 0
        while attempts < max_retries:
            attempts += 1

            # Send the takeoff message
            self.drone.mav.send(takeoff_message)
            logger.info(f"Takeoff attempt {attempts}/{max_retries} to {target_altitude}m")

            # Wait for acknowledgment
            ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=1.0)

            if ack and ack.command == dialect.MAV_CMD_NAV_TAKEOFF:
                success = (ack.result == dialect.MAV_RESULT_ACCEPTED)
                if success:
                    logger.success(f"Takeoff command accepted! Target altitude: {target_altitude}m")
                    self.altitude = target_altitude
                    return True
                else:
                    # Log the specific failure reason if available
                    result_name = dialect.enums['MAV_RESULT'][ack.result].name if ack.result in dialect.enums['MAV_RESULT'] else f"Unknown ({ack.result})"
                    logger.warning(f"Takeoff attempt {attempts} failed: {result_name}")
            else:
                logger.warning(f"No acknowledgment received for takeoff attempt {attempts}")

            # Check if we should retry
            if attempts < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Takeoff failed after {max_retries} attempts")

        return False

    def fly_to_here(self, distance=5.0, max_retries=3):
        """
        Command the drone to fly to a location in the direction of current heading
        
        Args:
            distance (float): Distance to fly in meters (default: 5.0m)
            max_retries (int): Maximum number of retry attempts for commands
            retry_delay (float): Delay between retries in seconds
            timeout (int): Maximum time to wait for reaching the target in seconds
            
        Returns:
            bool: True if command accepted and target reached, False otherwise
        """
        import math
        import time
        
        if not self.drone:
            logger.error("No drone connection")
            return False
        
        # Get current position and heading
        status = self.get_drone_status()
        
        if not status.get('position') or not status.get('heading'):
            logger.error("Cannot get current position or heading")
            return False
        
        current_lat, current_lon = status['position']
        heading = status['heading']
        
        if heading is None:
            logger.error("Cannot determine current heading")
            return False
        
        # Convert heading to radians for calculation
        heading_rad = math.radians(heading)
        
        # Earth radius in meters
        earth_radius = 6378137.0
        
        # Calculate target position using great circle formula
        # Convert distance from meters to radians
        angular_distance = distance / earth_radius
        
        # Calculate target position
        target_lat = math.asin(
            math.sin(math.radians(current_lat)) * math.cos(angular_distance) +
            math.cos(math.radians(current_lat)) * math.sin(angular_distance) * math.cos(heading_rad)
        )
        
        target_lon = math.radians(current_lon) + math.atan2(
            math.sin(heading_rad) * math.sin(angular_distance) * math.cos(math.radians(current_lat)),
            math.cos(angular_distance) - math.sin(math.radians(current_lat)) * math.sin(target_lat)
        )
        
        # Convert target position back to degrees
        target_lat = math.degrees(target_lat)
        target_lon = math.degrees(target_lon)
        
        logger.info(f"Current position: Lat {current_lat:.6f}, Lon {current_lon:.6f}, Heading {heading}°")
        logger.info(f"Target position: Lat {target_lat:.6f}, Lon {target_lon:.6f}, Distance {distance}m")
        
        # Set flight mode to GUIDED
        if not self.set_flight_mode(FlightMode.GUIDED):
            logger.error("Failed to set GUIDED mode, aborting flight")
            return False
        
        # Wait for mode change
        time.sleep(1)
        
        # Check if drone is armed
        if not self.is_armed:
            logger.info("Drone not armed, attempting to arm...")
            if not self.arm():
                logger.error("Failed to arm drone, aborting flight")
                return False
            # Wait for arming
            time.sleep(1)
        
        # Convert lat/lon to int format expected by MAVLink (degrees * 1e7)
        lat_int = int(target_lat * 1e7)
        lon_int = int(target_lon * 1e7)
        
        # Default altitude: use current + 2m if available, otherwise 10m
        alt = (status.get('altitude', 0) + 2) if status.get('altitude') is not None else 10.0
        
        # Create mission item message for moving to target position
        # We're using MAV_CMD_NAV_WAYPOINT command
        mission_item = dialect.MAVLink_mission_item_int_message(
            target_system=self.drone.target_system,
            target_component=self.drone.target_component,
            seq=0,                                   # Sequence number
            frame=dialect.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,  # Altitude relative to home
            command=dialect.MAV_CMD_NAV_WAYPOINT,    # Go to waypoint command
            current=2,                               # Guided mode waypoint (2 indicates "guided mode")
            autocontinue=1,                          # Auto continue to next waypoint
            param1=0,                                # Hold time (seconds)
            param2=2.0,                              # Acceptance radius (meters)
            param3=0,                                # Pass by waypoint (0 = fixed location)
            param4=0,                                # Desired yaw angle (NaN = unchanged)
            x=lat_int,                               # Latitude (degrees * 1e7)
            y=lon_int,                               # Longitude (degrees * 1e7)
            z=alt                                    # Altitude (meters, relative to home)
        )
        

        success = False
   
        # Send the mission item
        self.drone.mav.send(mission_item)
        
        # Wait for acknowledgment 
        ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=2.0)
        
        if ack and (ack.command == dialect.MAV_CMD_NAV_WAYPOINT or 
                    ack.command == dialect.MAV_CMD_MISSION_START):
            if ack.result == dialect.MAV_RESULT_ACCEPTED:
                logger.success("Waypoint command accepted!")
                success = True
            else:
                # Log the specific failure reason if available
                result_name = dialect.enums['MAV_RESULT'][ack.result].name if ack.result in dialect.enums['MAV_RESULT'] else f"Unknown ({ack.result})"
                logger.warning(f"Waypoint attempt failed: {result_name}")
        else:
            logger.warning("No acknowledgment received for waypoint")
        
        
        if not success:
            logger.error(f"Failed to send waypoint command after {max_retries} attempts")
            return False
        
        
        """
        start_time = time.time()
        reached_target = False
        last_distance = float('inf')
        
        # Continue checking position until timeout or target reached
        while time.time() - start_time < timeout and not reached_target:
            # Get current position
            status = self.get_drone_status()
            
            if status.get('position'):
                current_lat, current_lon = status['position']
                
                # Calculate distance to target using Haversine formula
                current_lat_rad = math.radians(current_lat)
                current_lon_rad = math.radians(current_lon)
                target_lat_rad = math.radians(target_lat)
                target_lon_rad = math.radians(target_lon)
                
                # Haversine formula
                dlon = target_lon_rad - current_lon_rad
                dlat = target_lat_rad - current_lat_rad
                a = math.sin(dlat/2)**2 + math.cos(current_lat_rad) * math.cos(target_lat_rad) * math.sin(dlon/2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                distance_to_target = earth_radius * c  # in meters
                
                # Check if we're close enough to target (within 2m)
                acceptance_radius = 2.0  # meters
                if distance_to_target <= acceptance_radius:
                    reached_target = True
                    logger.success(f"Target reached! Final distance: {distance_to_target:.1f}m")
                    break
                
                # Only log if distance has changed significantly
                if abs(distance_to_target - last_distance) > 0.5:
                    logger.info(f"Distance to target: {distance_to_target:.1f}m")
                    last_distance = distance_to_target
            
            # Short sleep to prevent CPU overuse
            time.sleep(0.5)
        
        # Check if we timed out
        if not reached_target:
            logger.warning(f"Timeout reached ({timeout}s). Drone did not reach target.")
            return False
        
        logger.success("Fly to waypoint completed successfully!")
        return True
        """
        

    def land(self, max_retries=3, retry_delay=2):
        """
        Command the drone to land with retry capability
        Args:
            max_retries (int): Maximum number of retry attempts
            retry_delay (float): Delay between retries in seconds
        Returns:
            bool: True if land command accepted, False otherwise
        """
        if not self.drone:
            logger.error("No drone connection")
            return False

        # Create land command message
        land_message = dialect.MAVLink_command_long_message(
            target_system=self.drone.target_system,
            target_component=self.drone.target_component,
            command=dialect.MAV_CMD_NAV_LAND,
            confirmation=0,
            param1=0,
            param2=0,
            param3=0,
            param4=0,
            param5=0,
            param6=0,
            param7=0
        )

        # Try land with retries using while loop
        attempts = 0
        while attempts < max_retries:
            attempts += 1

            # Send the land message
            self.drone.mav.send(land_message)
            logger.info(f"Land attempt {attempts}/{max_retries}")

            # Wait for acknowledgment
            ack = self.drone.recv_match(type='COMMAND_ACK', blocking=True, timeout=1.0)

            if ack and ack.command == dialect.MAV_CMD_NAV_LAND:
                success = (ack.result == dialect.MAV_RESULT_ACCEPTED)
                if success:
                    logger.success("Land command accepted!")
                    return True
                else:
                    # Log the specific failure reason if available
                    result_name = dialect.enums['MAV_RESULT'][ack.result].name if ack.result in dialect.enums['MAV_RESULT'] else f"Unknown ({ack.result})"
                    logger.warning(f"Land attempt {attempts} failed: {result_name}")
            else:
                logger.warning(f"No acknowledgment received for land attempt {attempts}")

            # Check if we should retry
            if attempts < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Land command failed after {max_retries} attempts")

        return False

    def set_flight_mode(self, mode):
        """
        Set the flight mode of the drone
        Args:
            mode (str or FlightMode): Flight mode to set
        Returns:
            bool: True if mode change successful, False otherwise
        """
        if not self.drone:
            logger.error("No drone connection")
            return False

        try:
            # Convert to FlightMode enum if string is provided
            if isinstance(mode, str):
                mode_enum = FlightMode.from_string(mode)
                if not mode_enum:
                    logger.error(f"Invalid flight mode: {mode}")
                    return False
            else:
                mode_enum = mode

            # Get mode string for mavlink
            mode_str = FlightMode.to_string(mode_enum)

            # Using mavutil's set_mode, as dialect doesn't provide a direct way to set mode
            # with a MAVLink_command_long_message
            self.drone.set_mode(mode_str)
            self.flight_mode = mode_enum
            logger.success(f"Flight mode set to {mode_str}")
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

            # Create RC channels override message
            # Note: This is not a command_long, but a different message type
            # We keep using the drone.mav.rc_channels_override_send method for this
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
            FlightMode: Current flight mode enum, or None if not connected
        """
        if not self.drone:
            return None

        try:
            # Create request message command
            request_message = dialect.MAVLink_command_long_message(
                target_system=self.drone.target_system,
                target_component=self.drone.target_component,
                command=dialect.MAV_CMD_REQUEST_MESSAGE,
                confirmation=0,
                param1=dialect.MAVLINK_MSG_ID_HEARTBEAT,  # Message ID for heartbeat
                param2=0,
                param3=0,
                param4=0,
                param5=0,
                param6=0,
                param7=0
            )

            # Send the request message
            self.drone.mav.send(request_message)

            # Wait for heartbeat message to get mode
            msg = self.drone.recv_match(type='HEARTBEAT', blocking=True, timeout=1.0)
            if msg:
                # Convert mode to string using MAVLink mode mapping
                custom_mode = msg.custom_mode
                flight_mode_str = mavutil.mode_mapping_acm.get(custom_mode)

                if flight_mode_str:
                    # Convert to FlightMode enum and update internal tracking
                    try:
                        flight_mode_enum = FlightMode.from_string(flight_mode_str)
                        self.flight_mode = flight_mode_enum
                        logger.info(f"Current flight mode: {flight_mode_str}")
                        return flight_mode_enum
                    except ValueError:
                        logger.warning(f"Unknown flight mode string: {flight_mode_str}")
                        # Still update the internal string representation
                        self.flight_mode = flight_mode_str
                        return flight_mode_str
                else:
                    logger.warning("Couldn't determine flight mode from heartbeat")
            else:
                logger.warning("Couldn't retrieve flight mode - no heartbeat received")

            # Return last known mode if available
            return self.flight_mode

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

        # Convert enum to string for display if needed
        if isinstance(self.flight_mode, FlightMode):
            mode_display = self.flight_mode.value
        elif isinstance(self.flight_mode, str):
            mode_display = self.flight_mode
        else:
            mode_display = "Unknown"

        # Compile status information
        status = {
            'connected': True,
            'armed': self.is_armed,
            'mode': mode_display,
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
            print("Arming drone...")
            if self.drone_controller.arm():
                print("Drone armed successfully")
            else:
                print("Arming failed")

    def do_disarm(self, arg):
        """Disarm the drone"""
        if self._check_connection():
            print("Disarming drone...")
            if self.drone_controller.disarm():
                print("Drone disarmed successfully")
            else:
                print("Disarming failed")

    def do_flytohere(self, arg):
        """
        Command the drone to fly specified distance in current heading direction
        Usage: flytohere [distance]
        Example: flytohere 10       - Fly forward 10 meters
        Default distance: 5 meters
        """
        if not self._check_connection():
            return
        
        try:
            # Parse distance argument if provided, otherwise use default
            if arg:
                distance = float(arg)
            else:
                distance = 5.0
            
            # Check if drone is armed
            if not self.drone_controller.is_armed:
                print("Arming drone...")
                if not self.drone_controller.arm():
                    print("Failed to arm drone. Aborting flight.")
                    return
                time.sleep(1)  # Wait a moment after arming

            print(f"Flying {distance} meters in current heading direction...")
            
            # Call the fly_to_here method
            if self.drone_controller.fly_to_here(distance=distance):
                print(f"Flight completed successfully!")
            else:
                print("Flight command failed or target not reached")
                
        except ValueError:
            print("Error: Invalid distance value. Usage: flytohere [distance]")
            print("Example: flytohere 10  - Fly forward 10 meters")
        except Exception as e:
            print(f"Error executing flight command: {str(e)}")

    def do_mode(self, arg):
        """
        Set flight mode
        Usage: mode <mode_name>
        Example: mode GUIDED
        Available modes: STABILIZE, GUIDED, AUTO, LOITER, RTL, LAND, etc.
        """
        if not arg:
            print("Error: Please specify a flight mode")
            print("Available modes:")
            for mode in FlightMode:
                print(f"  {mode.value}")
            return

        if self._check_connection():
            try:
                # Try to convert to enum to validate
                mode = arg.upper()
                valid_modes = [m.value for m in FlightMode]

                if mode not in valid_modes:
                    print(f"Invalid mode: {arg}")
                    print("Available modes:")
                    for valid_mode in valid_modes:
                        print(f"  {valid_mode}")
                    return

                self.drone_controller.set_flight_mode(mode)
            except Exception as e:
                print(f"Error setting mode: {str(e)}")

    def do_takeoff(self, arg):
        """
        Take off to specified altitude
        Usage: takeoff <altitude>
        Example: takeoff 10       - Take off to 10m altitude
        """
        try:
            # Parse altitude argument
            altitude = float(arg)

            if self._check_connection():
                if not self.drone_controller.is_armed:
                    print("Arming drone...")
                    if not self.drone_controller.arm():
                        print("Failed to arm drone. Aborting takeoff.")
                        return
                    time.sleep(1)

                print(f"Taking off to {altitude}m...")
                if self.drone_controller.takeoff(altitude):
                    print(f"Takeoff command accepted. Climbing to {altitude}m")
                else:
                    print("Takeoff command failed")
        except ValueError:
            print("Error: Invalid altitude. Usage: takeoff <altitude>")
            print("Example: takeoff 10  - Take off to 10m altitude")

    def do_land(self, arg):
        """
        Command the drone to land
        Usage: land
        """
        if self._check_connection():
            print("Landing...")
            if self.drone_controller.land():
                print("Land command accepted. Drone is landing...")
            else:
                print("Land command failed")

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
        Example: status 5 (shows status for 5 seconds)
        """
        if not self._check_connection():
            return

        try:
            timeout = int(arg) if arg else 3
        except ValueError:
            timeout = 3

        print("Monitoring drone status for", timeout, "seconds:")
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.drone_controller.get_drone_status()

            # Format mode display - handle case where mode might be None, string, or enum
            mode_display = status['mode']
            if mode_display is None:
                mode_display = "Unknown"

            print(f"Armed: {status['armed']}, Mode: {mode_display}, Alt: {status['altitude']:.1f}m")
            if status.get('position'):
                print(f"Position: Lat {status['position'][0]:.6f}, Lon {status['position'][1]:.6f}")
            time.sleep(1)

        print("Status monitoring ended")

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


def main():
    try:
        DroneShell().cmdloop()
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        if hasattr(DroneShell(), 'drone_controller') and DroneShell().drone_controller:
            DroneShell().drone_controller.cleanup()


if __name__ == "__main__":
    main()
