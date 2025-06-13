import logging
import time
import unittest
from unittest.mock import patch, MagicMock, call

from libs import drone_v2x

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class TestDroneV2X(unittest.TestCase):
    def setUp(self):
        drone_v2x._initialized = False
        drone_v2x._send_fd = 0
        drone_v2x._recv_fd = 0
        drone_v2x._myself_addr = 0
        drone_v2x._config = (0, 0, drone_v2x.Role.NONE)
        drone_v2x._autoack = True
        drone_v2x._debug_print_on = False
        drone_v2x._init_callback = None
    
    def tearDown(self):
        try:
            if hasattr(drone_v2x, '_send_fd') and drone_v2x._send_fd:
                drone_v2x._send_fd.close()
            if hasattr(drone_v2x, '_recv_fd') and drone_v2x._recv_fd:
                drone_v2x._recv_fd.close()
        except Exception:
            pass

class TestGroupSetting(TestDroneV2X):
    
    def test_set_group_invalid_range(self):
        """Test setting invalid group numbers"""
        with self.assertRaises(ValueError):
            drone_v2x.set_group(0)
        
        with self.assertRaises(ValueError):
            drone_v2x.set_group(251)

    @patch('socket.socket')
    def test_set_group_leader_role(self, mock_socket):
        """Test setting group for leader role (group <= 10)"""
        mock_send_socket = MagicMock()
        mock_send_socket.sendto.return_value = 4
        mock_socket.return_value = mock_send_socket
        
        drone_v2x._config = (1, 5, drone_v2x.Role.GCS)
        
        drone_v2x.set_group(8)
        
        # Verify command was sent
        mock_send_socket.sendto.assert_called_once()
        args, kwargs = mock_send_socket.sendto.call_args
        packet, addr = args
        
        self.assertEqual(addr, drone_v2x._V2X_CMD_ADDR)
        self.assertEqual(packet[2], drone_v2x.Role.LEADER.value)  # role
        self.assertEqual(packet[3], 8)  # master_id
        
        # Verify config was updated
        self.assertEqual(drone_v2x._config[0], 8)
        self.assertEqual(drone_v2x._config[2], drone_v2x.Role.LEADER)

    @patch('socket.socket')
    def test_set_group_slave_role(self, mock_socket):
        """Test setting group for slave role (group > 10)"""
        mock_send_socket = MagicMock()
        mock_send_socket.sendto.return_value = 4
        mock_socket.return_value = mock_send_socket
        
        drone_v2x._config = (1, 5, drone_v2x.Role.GCS)
        
        drone_v2x.set_group(15)
        
        args, kwargs = mock_send_socket.sendto.call_args
        packet, addr = args
        
        self.assertEqual(packet[2], drone_v2x.Role.SLAVE.value)  # role
        self.assertEqual(packet[3], 15)  # master_id

def main():

    def _callback(status: int, message: str):
        if status == 1:
            logging.info(f'init success, msg: {message}')
        else:
            logging.info(f'init not ready.., msg: {message}')


    drone_v2x.set_init_callback(callback=_callback)
    drone_v2x.init()
    drone_v2x.set_group(2)
    logging.info(f"group: {drone_v2x.get_my_group()}, id: {drone_v2x.get_my_id()}")
    drone_v2x.set_group(3)
    logging.info(f"group: {drone_v2x.get_my_group()}, id: {drone_v2x.get_my_id()}")


    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()