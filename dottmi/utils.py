# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022-2025 Thomas Winkler <thomas.winkler@gmail.com>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
###############################################################################
import logging
import os
import signal
import struct
import threading
from collections import deque
from typing import Union, List, Any

from dott_ng_runtime.dott_runtime import DottRuntime

from dottmi.dottexceptions import DottException

log = logging.getLogger('DOTT')


def log_setup() -> None:
    # suppress log debug/info from pygdbmi
    logger = logging.getLogger('pygdbmi')
    logger.setLevel(logging.ERROR)
    # suppress log debug/info output on a general basis
    logging.getLogger().setLevel(logging.ERROR)
    # configure DOTT log level
    logging.getLogger('DOTT').setLevel(logging.DEBUG)


# -------------------------------------------------------------------------------------------------
def DOTT_LABEL(name: str) -> str:
    ret = f'DOTT_LABEL_{name}'
    return ret


# -------------------------------------------------------------------------------------------------
# used as decorator to implement singleton pattern
def singleton(cls):
    instances = {}

    def _singleton(*args, **kw):
        if cls not in instances:
            instances[cls] = cls(*args, **kw)
        return instances[cls]

    return _singleton


# -------------------------------------------------------------------------------------------------
class DottConvert(object):
    @staticmethod
    def bytes_to_uint32(data: bytes, byte_order: str = 'little') -> Union[int, List[int]]:
        """
        This function takes a bytes variable and converts its content to an int, or if data is longer than four
        bytes, to an int list. The bytes are interpreted as uint32 integers.
        Args:
            data: Bytes to be converted to int / int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
        An int or an int list if data is longer than four bytes.
        """
        if (len(data) % 4) != 0:
            raise ValueError(f'Data shall have a length which is a multiple of 4!')

        if byte_order == 'little':
            ret_val = struct.unpack('<%dI' % (len(data) / 4), data)
        elif byte_order == 'big':
            ret_val = struct.unpack('>%dI' % (len(data) / 4), data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        if len(ret_val) == 1:
            return ret_val[0]
        else:
            return list(ret_val)

    @staticmethod
    def bytes_to_uint16(data: bytes, byte_order: str = 'little') -> Union[int, List[int]]:
        """
        This function takes a bytes variable and converts its content to an int, or if data is longer than two
        bytes, to an int list. The bytes are interpreted as uint16 integers.
        Args:
            data: Bytes to be converted to int / int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
        An int or an int list if data is longer than two bytes.
        """
        if (len(data) % 2) != 0:
            raise ValueError(f'Data shall have a length which is a multiple of 2!')

        if byte_order == 'little':
            ret_val = struct.unpack('<%dH' % (len(data) / 2), data)
        elif byte_order == 'big':
            ret_val = struct.unpack('>%dH' % (len(data) / 2), data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        if len(ret_val) == 1:
            return ret_val[0]
        else:
            return list(ret_val)

    @staticmethod
    def bytes_to_uint8(data: bytes, byte_order: str = 'little') -> Union[int, List[int]]:
        """
        This function takes a bytes variable and converts its content to an int, or if data is longer than one
        byte, to and int list. The bytes are interpreted as uint8 integers.
        Args:
            data: Bytes to be converted to int / int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
        An int or an int list if data is longer than one byte.
        """
        if byte_order == 'little':
            ret_val = struct.unpack('<%dB' % (len(data)), data)
        elif byte_order == 'big':
            ret_val = struct.unpack('>%dB' % (len(data)), data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        if len(ret_val) == 1:
            return ret_val[0]
        else:
            return list(ret_val)

    @staticmethod
    def bytes_to_int32(data: bytes, byte_order: str = 'little') -> Union[int, List[int]]:
        """
        This function takes a bytes variable and converts its content to an int, or if data is longer than four
        bytes, to an int list. The bytes are interpreted as int32 integers.
        Args:
            data: Bytes to be converted to int / int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
        An int or an int list if data is longer than four bytes.
        """
        if (len(data) % 4) != 0:
            raise ValueError(f'Data shall have a length which is a multiple of 4!')

        if byte_order == 'little':
            ret_val = struct.unpack('<%di' % (len(data) / 4), data)
        elif byte_order == 'big':
            ret_val = struct.unpack('>%di' % (len(data) / 4), data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        if len(ret_val) == 1:
            return ret_val[0]
        else:
            return list(ret_val)

    @staticmethod
    def bytes_to_int16(data: bytes, byte_order: str = 'little') -> Union[int, List[int]]:
        """
        This function takes a bytes variable and converts its content to an int, or if data is longer than two
        bytes, to an int list. The bytes are interpreted as int16 integers.
        Args:
            data: Bytes to be converted to int / int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
        An int or an int list if data is longer than two bytes.
        """
        if (len(data) % 2) != 0:
            raise ValueError(f'Data shall have a length which is a multiple of 2!')

        if byte_order == 'little':
            ret_val = struct.unpack('<%dh' % (len(data) / 2), data)
        elif byte_order == 'big':
            ret_val = struct.unpack('>%dh' % (len(data) / 2), data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        if len(ret_val) == 1:
            return ret_val[0]
        else:
            return list(ret_val)

    @staticmethod
    def bytes_to_int8(data: bytes, byte_order: str = 'little') -> Union[int, List[int]]:
        """
        This function takes a bytes variable and converts its content to an int, or if data is longer than one
        byte, to an int list. The bytes are interpreted as int8 integers.
        Args:
            data: Bytes to be converted to int / int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
        An int or an int list if data is longer than two bytes.
        """
        if byte_order == 'little':
            ret_val = struct.unpack('<%db' % (len(data)), data)
        elif byte_order == 'big':
            ret_val = struct.unpack('>%db' % (len(data)), data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        if len(ret_val) == 1:
            return ret_val[0]
        else:
            return list(ret_val)

    @staticmethod
    def uint32_to_bytes(data: Union[int, List[int]], byte_order: str = 'little') -> bytes:
        """
        This function takes either an int or an int list and converts the integer(s) to bytes. The integers are
        interpreted as uint32 integers.
        Args:
            data: An int or an int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
            A bytes object containing the serialized integer data.
        """
        if isinstance(data, int):
            data = [data]
        if byte_order == 'little':
            ret_val = struct.pack('<%dI' % len(data), *data)
        elif byte_order == 'big':
            ret_val = struct.pack('>%dI' % len(data), *data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        return ret_val

    @staticmethod
    def uint16_to_bytes(data: Union[int, List[int]], byte_order: str = 'little') -> bytes:
        """
        This function takes either an int or an int list and converts the integer(s) to bytes. The integers are
        interpreted as uint16 integers.
        Args:
            data: An int or an int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
            A bytes object containing the serialized integer data.
        """
        if isinstance(data, int):
            data = [data]
        if byte_order == 'little':
            ret_val = struct.pack('<%dH' % len(data), *data)
        elif byte_order == 'big':
            ret_val = struct.pack('>%dH' % len(data), *data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        return ret_val

    @staticmethod
    def uint8_to_bytes(data: Union[int, List[int]], byte_order: str = 'little') -> bytes:
        """
        This function takes either an int or an int list and converts the integer(s) to bytes. The integers are
        interpreted as uint8 integers.
        Args:
            data: An int or an int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
            A bytes object containing the serialized integer data.
        """
        if isinstance(data, int):
            data = [data]
        if byte_order == 'little':
            ret_val = struct.pack('<%dB' % len(data), *data)
        elif byte_order == 'big':
            ret_val = struct.pack('>%dB' % len(data), *data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        return ret_val

    @staticmethod
    def int32_to_bytes(data: Union[int, List[int]], byte_order: str = 'little') -> bytes:
        """
        This function takes either an int or an int list and converts the integer(s) to bytes. The integers are
        interpreted as int32 integers.
        Args:
            data: An int or an int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns: A bytes object containing the serialized integer data.
        """
        if isinstance(data, int):
            data = [data]
        if byte_order == 'little':
            ret_val = struct.pack('<%di' % len(data), *data)
        elif byte_order == 'big':
            ret_val = struct.pack('>%di' % len(data), *data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        return ret_val

    @staticmethod
    def int16_to_bytes(data: Union[int, List[int]], byte_order: str = 'little') -> bytes:
        """
        This function takes either an int or an int list and converts the integer(s) to bytes. The integers are
        interpreted as int16 integers.
        Args:
            data: An int or an int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns: A bytes object containing the serialized integer data.
        """
        if isinstance(data, int):
            data = [data]
        if byte_order == 'little':
            ret_val = struct.pack('<%dh' % len(data), *data)
        elif byte_order == 'big':
            ret_val = struct.pack('>%dh' % len(data), *data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        return ret_val

    @staticmethod
    def int8_to_bytes(data: Union[int, List[int]], byte_order: str = 'little') -> bytes:
        """
        This function takes either an int or an int list and converts the integer(s) to bytes. The integers are
        interpreted as int8 integers.
        Args:
            data: An int or an int list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns: A bytes object containing the serialized integer data.
        """
        if isinstance(data, int):
            data = [data]
        if byte_order == 'little':
            ret_val = struct.pack('<%db' % len(data), *data)
        elif byte_order == 'big':
            ret_val = struct.pack('>%db' % len(data), *data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        return ret_val

    @staticmethod
    def float_to_bytes(data: Union[float, List[float]], byte_order: str = 'little') -> bytes:
        """
        This function takes either an float or a float list and converts the float(s) to bytes. The floats are
        interpreted as 32bit floats.
        Args:
            data: An float or an float list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns: A bytes object containing the serialized float data.
        """
        if isinstance(data, float):
            data = [data]
        if byte_order == 'little':
            ret_val = struct.pack('<%df' % len(data), *data)
        elif byte_order == 'big':
            ret_val = struct.pack('>%df' % len(data), *data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        return ret_val

    @staticmethod
    def bytes_to_float(data: bytes, byte_order: str = 'little') -> Union[float, List[float]]:
        """
        This function takes a bytes variable and converts its content to a float, or if data is longer than four
        bytes, to a float list. The bytes are interpreted as 32bit floats.
        Args:
            data: Bytes to be converted to float / float list.
            byte_order: Either 'little' for little endian (default) or 'big' for big endian.

        Returns:
        A float or and float list if data is longer than four bytes.
        """
        if (len(data) % 4) != 0:
            raise ValueError(f'Data shall have a length which is a multiple of 4!')

        if byte_order == 'little':
            ret_val = struct.unpack('<%df' % (len(data) / 4), data)
        elif byte_order == 'big':
            ret_val = struct.unpack('>%df' % (len(data) / 4), data)
        else:
            raise ValueError(f'Unsupported byte order ({byte_order})!')

        if len(ret_val) == 1:
            return ret_val[0]
        else:
            return list(ret_val)


# -------------------------------------------------------------------------------------------------
def cast_str(data: Union[str, bytes]) -> Union[int, float, bool, str]:
    """
    This function attempts to 'smart-cast' data (received from GDB) as string into Python int, float, bool or, if
    other conversion fail, str types.
    Args:
        data: Data string to the interpreted/casted.

    Returns:
        Returns a Python int, float, bool or str containing the result of the cast operation.
    """
    if type(data) == bytes:
        data = data.decode('ascii')

    # single chars are returned by MI in a format like this: "2 '\\002'"
    # if this format is detected, it is split up such that an int is returned
    if " '" in str(data):
        data = str(data).split(" '")[0]

    if 'false' in str(data).lower():
        return False
    elif 'true' in str(data).lower():
        return True

    try:
        if data.startswith('@0x'):
            # GDB returns CPP references (e.g., "MyFoo& GetInstance();" ) as @0xAABBCCDD). Stripping the leading @ here.
            data = data.lstrip('@')

        if data.startswith('0x'):
            tmp = data
            if ' <' in tmp:
                # function pointers typically are return in this format '0x0304 <func_name>'
                tmp = tmp.split(' <')[0]
            elif ' "' in tmp:
                # character pointers (char* and sometimes uint8_t*) are return in this format '0x65 ""'
                tmp = tmp.split(' "')[0]
            return int(tmp, 16)
    except Exception:
        # if the data is not just a 'pure' hex value (e.g., more (string) data after the hex value)
        pass

    for fn in (int, float):
        try:
            return fn(data)
        except ValueError:
            pass
        except TypeError:
            pass
    return data  # return as string


# -------------------------------------------------------------------------------------------------
class BlockingDict(object):
    def __init__(self):
        self._items = {}
        self._cv = threading.Condition()

    def put(self, key, value):
        with self._cv:
            self._items[key] = value
            self._cv.notify_all()

    def pop(self, key, timeout: float = None):
        with self._cv:
            while key not in self._items:
                new_item = self._cv.wait(timeout)
                if not new_item:
                    # timeout hit
                    raise TimeoutError

            return self._items.pop(key)


# -------------------------------------------------------------------------------------------------
class Network(object):

    _next_gdb_srv_port: int = 2331

    @classmethod
    def get_next_srv_port(cls, srv_addr: str) -> int:
        """
        Find the next triplet of free ("bind-able") TCP ports on the given server IP address.
        Ports are automatically advanced until a free port triplet is found.

        Args:
            srv_addr: IP address of the server.
        Returns:
            Returns the first port number of the discovered, free port triplet.
        """
        import socket

        port = cls._next_gdb_srv_port + 3
        sequentially_free_ports = 0
        start_port = 0

        while True:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind((srv_addr, port))
                sequentially_free_ports += 1
                if sequentially_free_ports == 1:
                    start_port = port
            except socket.error:
                # log.debug(f'Can not bind port {port} as it is already in use.')
                sequentially_free_ports = 0
            finally:
                s.close()

            if sequentially_free_ports > 2:
                # found 3 free ports in a row
                break

            port += 1
            if port >= 65535:
                raise DottException(f'Unable do find three (consecutive) free ports for IP {srv_addr}!')

        cls._next_gdb_srv_port = start_port + sequentially_free_ports
        if cls._next_gdb_srv_port > 65500:
            # wrap around for next invocation
            cls._next_gdb_srv_port = 2331
        return start_port


# -------------------------------------------------------------------------------------------------
class InMemoryDebugCapture:
    """
    In-memory debug capture records provided entries in a memory (RAM) buffer.
    It does not immediately print the recorded entries and therefore reduces the impact on runtime timing. This might
    be important for low-level problem analysis. Capturing is done in a circular buffer of pre-defined size.
    """

    def __init__(self, enabled: bool = False, num_records: int = 60):
        self._enabled: bool = enabled
        self._capture_queue: deque = deque(maxlen=num_records)

    @property
    def enabled(self) -> bool:
        """
        Returns enable status.
        """
        return self._enabled

    @enabled.setter
    def enabled(self, enabled: bool) -> None:
        """
        Enable or disable debug capturing.
        Args:
            enabled: True to enable, False to disable.
        """
        self._enabled = enabled

    def record(self, entry: Any) -> None:
        """
        Records the provided entry in the internal queue.
        :param entry: Entry to be added to the capture queue.
        """
        if self._enabled:
            self._capture_queue.append(entry)

    def dump(self) -> None:
        """
        Dumps (prints) the recorded entries. If running in pytest this might require "-s" command line option.
        """
        if self._enabled:
            print(f'{os.linesep}{os.linesep}-------- Debug Capture Dump --------{os.linesep}')
            for entry in self._capture_queue:
                print(entry)


# -------------------------------------------------------------------------------------------------
class ExceptionPropagator:
    """
    This class provides functionality to propagate exceptions from threads to the main thread.
    Propagation is implemented by means of signal.SIGABRT which is raised by the sub thread.
    """
    _exception: Exception | None = None
    # _exception_lock: threading.Lock = threading.Lock()

    @classmethod
    def _sig_handler(cls, signum, frame):
        if cls._exception:
            raise cls._exception

    @classmethod
    def setup(cls):
        """
        Sets up the signal handler. Should be called from main thread.
        """
        if threading.current_thread().name != 'MainThread':
            log.warning('Signal handler setup should be called from main thread!')
        signal.signal(signal.SIGABRT, cls._sig_handler)

    @classmethod
    def propagate_exception(cls, exc: Exception):
        """
        Propagates teh given exception ecx to the main thread. Te setup method is
        expected to be called before by the main thread.
        """
        cls._exception = exc
        signal.raise_signal(signal.SIGABRT)
        # assert cls._exception == None


# -------------------------------------------------------------------------------------------------
# Decorators

def requires_rt_ge_2(func):
    """
    This decorator is used to mark functions which at least need DOTT.NG runtime verison 2 or higher.
    """
    def wrapper(*args, **kwargs):
        major = int(DottRuntime.VERSION.split('.')[0])
        if major < 2:
            raise DottException(f'For using function "{func.__name__}" a DOTT.NG runtime version greater or '
                                f'equal 2.y.z is required!')
        res = func(*args, **kwargs)
        return res
    return wrapper
