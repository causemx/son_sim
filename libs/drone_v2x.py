import enum
import random
import socket
import struct
from typing import Callable, Optional

#region Constants
class Role(enum.Enum):
    NONE = 0
    GCS = 1
    LEADER = 2
    SLAVE = 3

_PREFIX = 0xA5
_DATA = 0x01
_ACK = 0x02
_COMMAND = 0x05
_REPORT = 0x07

_V2X_LOCAL_IP = "192.168.1.1"
_V2X_LOCAL_PORT = 6001
_V2X_SOM_IP = "192.168.1.3"
_V2X_SOM_PORT = 6003
_V2X_CMD_PORT = 6005
_V2X_RPT_PORT = 6007

_V2X_LOCAL_ADDR = (_V2X_LOCAL_IP, _V2X_LOCAL_PORT)
_V2X_RPT_ADDR = (_V2X_LOCAL_IP, _V2X_RPT_PORT)
_V2X_PEER_ADDR = (_V2X_SOM_IP, _V2X_SOM_PORT)
_V2X_CMD_ADDR = (_V2X_SOM_IP, _V2X_CMD_PORT)
#endregion

#region Global variables
_send_fd = 0
_recv_fd = 0
_myself_addr = 0
_config = (0, 0, Role.NONE)
_autoack = True
#endregion

#region debug
_debug_print_on = False

_init_callback: Optional[Callable[[int, str], None]] = None

def _debug_print(*args, **kwargs):
    global _debug_print_on
    if _debug_print_on:
        print(*args, **kwargs)

def set_debug(onoff):
    global _debug_print_on
    _debug_print_on = onoff

def _dump_bytes(buf):
    length = len(buf)
    for i in range(length):
        print(f"{buf[i]:02X}", end=" ")
        if i % 16 == 7:
            print(" ", end=" ")
        if i % 16 == 15:
            print()
    return
#endregion

def set_init_callback(callback: Callable[[int, str], None]):
    global _init_callback
    _init_callback = callback

def _notify_init(status: int, message: str):
    global _init_callback
    if _init_callback is not None:
        try:
            _init_callback(status, message)
        except Exception as e:
            print(f"Callback error: {e}")

#region init
_initialized = False
def _do_init(group, id, role):
    global _send_fd, _recv_fd, _config, _myself_addr
    _myself_addr = group * 256 + id
    _config = (group, id, role)
    _debug_print("init: Detected address is", _config, "and role is", Role(role).name)

    try:
        _send_fd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _recv_fd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _recv_fd.bind(_V2X_LOCAL_ADDR)
    except Exception as e:
        print(f"Bind error: {e}")
        raise e
    _debug_print("init: Sending/Receiving sockets binded.")


def init(force = False):
    global _initialized

    if _initialized and not force:
        _notify_init(1, "Already initialized")
        return True
    
    _notify_init(0, "Starting initialization...",)
    
    rpt_fd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rpt_fd.settimeout(10)
    
    '''
    try:
        rpt_fd.bind(_V2X_RPT_ADDR)
    except socket.error as e:
        _debug_print(f"Bind() error: {e}")
        _notify_init(0, f"Bind() error: {e}")
        return False
        # raise e
    '''
        
    _debug_print("init: Heartbeat socket binded, reading my address...")

    try_count = 3
    while True > 0:
        try:
            rpt_fd.bind(_V2X_RPT_ADDR)
            _notify_init(0, "Waiting for configuation...")

            buff, _ = rpt_fd.recvfrom(256)
            _debug_print("init: recvfrom() success.")
            
            if len(buff) > 2:
                if buff[2] == buff[3] and 0 < buff[2] < 11:
                    _do_init(buff[2], buff[3], Role.GCS)
                    break
                elif 0 < buff[2] < 11:
                    _do_init(buff[2], buff[3], Role.LEADER)
                    break
                elif 10 < buff[2] < 251:
                    _do_init(buff[2], buff[3], Role.SLAVE)
                    break
                else:
                    _debug_print("init: Unknown addr", buff[2], buff[3])
                    _notify_init(0, f"init: Unknown addr {buff[2]} {buff[3]}")
                    pass
        except socket.error as e:
            _debug_print(f"socket error: {e}")
            _notify_init(0, f"socket error: {e}")
            continue
        # try_count -= 1
        
    rpt_fd.close()
    _debug_print("init: Heartbeat socket closed.")

    if try_count <= 0:
        _notify_init(0, "Failed to get device configuration.")
        # raise Exception("Failed to get device configuration.")
    _initialized = True
    _notify_init(1, "init success")
    return True
#endregion

#region send/recv
def _send_ack(buffer):
    global _send_fd, _V2X_PEER_ADDR, _ACK
    buffer[1] = _ACK
    dst = buffer[2:4]
    src = buffer[4:6]
    buffer[2:4] = src
    buffer[4:6] = dst
    buffer[6:8] = b'\x00\x00'
    try:
        _send_fd.sendto(buffer[:16], _V2X_PEER_ADDR)
        _debug_print(f"send ACK to {dst[2]}.{dst[3]} success")
        #_dump_bytes(buffer[:16])
    except Exception as e:
        _debug_print(f"sendto(ACK) error: {e}")

def recv(bufsize = 1400, getack = False):
    global _recv_fd
    buffer = bytearray(bufsize)
    try:
        while (True):
            data, _ = _recv_fd.recvfrom(bufsize)
            buffer[:len(data)] = data
            if buffer[1] == _DATA:
                remote_addr = (buffer[4], buffer[5])
                payload = buffer[16:]
                _debug_print(f"recv DATA from {remote_addr} success: {payload.decode()}")
                if buffer[3] != 255 and _autoack:
                    _send_ack(buffer)
                return payload, remote_addr

            elif buffer[1] == _ACK:
                _debug_print(f"recv ACK from {buffer[4]}.{buffer[5]} success.")
                #_dump_bytes(buffer[:16])
                if getack:
                    return buffer, (buffer[4], buffer[5])
            else:
                _debug_print(f"recvfrom(UNKNOWN) success from {buffer[4]}.{buffer[5]}")

    except Exception as e:
        print(f"recvfrom() error: {e}")

def _pack_hdr(dst_addr, length, relay_addr = 0, reserved2 = 0):
    global _PREFIX, _DATA, _myself_addr
    dst = dst_addr if isinstance(dst_addr, int) else dst_addr[0] * 256 + dst_addr[1]
    relay = relay_addr if isinstance(relay_addr, int) else relay_addr[0] * 256 + relay_addr[1]
    return struct.pack('!BBHHHHHI', _PREFIX, _DATA, dst, _myself_addr, length, random.randint(0, 65535), relay, reserved2)

def send(payload, remote_addr, relay_addr = 0):
    global _send_fd, _V2X_PEER_ADDR
    packet = _pack_hdr(remote_addr, len(payload), relay_addr) + payload.encode()
    #_debug_print(f"message to send:", packet);

    try:
        ret = _send_fd.sendto(packet, _V2X_PEER_ADDR)
        _debug_print(f"send success to {remote_addr}: {payload}")
        return ret
    except Exception as e:
        _debug_print(f"sendto(DATA) error: {e}")
        raise e

#endregion

#region config
def get_my_group():
    global _config
    return _config[0]

def get_my_id():
    global _config
    return _config[1]

def get_my_role():
    global _config
    return _config[2]

def get_autoack():
    global _autoack
    return _autoack

def set_autoack(autoack):
    global _autoack
    _autoack = autoack

def _pack_cmd(role, master_id):
    return struct.pack('!BBBB', _PREFIX, _COMMAND, role.value, master_id)

def set_group(group):
    global _config, _myself_addr

    if (group < 1 or group > 250):
        raise ValueError("Invalid group number")
    
    try:
        send_fd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except socket.error as e:
        _debug_print(f"socket() error: {e}")
        raise e

    role = Role.SLAVE if group > 10 else Role.LEADER
    buff = _pack_cmd(role=role, master_id=group)

    try:
        # Send the message via UDP
        ret = send_fd.sendto(buff, _V2X_CMD_ADDR)
        if ret <= 0:
            _debug_print("sendto() error")
        else:
            _debug_print(f"sendto({buff[0]:02X} {buff[1]:02X} {buff[2]:02X} {buff[3]:02X}) success")
            _myself_addr = group * 256 + _config[1]
            _config = (group, _config[1], role)
    except socket.error as e:
        _debug_print(f"sendto() error: {e}")
    
    send_fd.close()
#endregion

if __name__ == "__main__":
    set_debug(True)
    init()