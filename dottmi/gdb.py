# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022-2024 Thomas Winkler <thomas.winkler@gmail.com>
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

import atexit
import os
import platform
import signal
import socket
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path

import psutil
from psutil import NoSuchProcess

from dottmi.dott_conf import DottConf
from dottmi.dottexceptions import DottException
from dottmi.gdb_mi import GdbMi
from dottmi.gdbcontrollerdott import GdbControllerDott
from dottmi.utils import log


class GdbServer(ABC):
    def __init__(self, addr, port):
        self._addr: str = addr
        self._port: int = port

    @property
    def addr(self):
        return self._addr

    @property
    def port(self):
        return self._port

    @abstractmethod
    def _launch(self, device_name: str):
        pass

    @abstractmethod
    def shutdown(self):
        pass


class GdbServerExternal(GdbServer):
    """
    This class represents an external (typically remote) GDB server instance. It is not started or managed by DOTT.
    Management of this GDB server instance is handled externally.
    """
    def __init__(self, addr, port):
        super().__init__(addr, port)

    def _launch(self, device_name: str):
        # remote GDB server instances are not managed by DOTT
        pass

    def shutdown(self):
        # remote GDB server instances are not managed by DOTT
        pass


class GdbServerJLink(GdbServer):
    def __init__(self, gdb_svr_binary: str, addr: str, port: int, device_name: str, interface: str, endian: str,
                 speed: str = '15000', serial_number: str = None, jlink_addr: str = None, jlink_script: str = None,
                 jlink_extconf: str = None):
        super().__init__(addr, port)
        self._srv_binary: str = gdb_svr_binary
        self._srv_process = None
        self._target_interface: str = interface
        self._target_endian: str = endian
        self._speed: str = speed
        self._serial_number: str = serial_number
        self._jlink_addr: str = jlink_addr
        self._jlink_script: str = jlink_script
        self._jlink_extconf: str = jlink_extconf
        # Popen.__del__ occasionally complains under Windows about invalid file handles on interpreter shutdown.
        # This is somewhat distracting and is silenced by a custom delete function.
        subprocess.Popen.__del_orig__ = subprocess.Popen.__del__
        subprocess.Popen.__del__ = GdbServerJLink._popen_del

        if self.addr is None:
            self._launch(device_name)

    @staticmethod
    def _popen_del(instance):
        try:
            instance.__del_orig__()
        except:
            pass

    def _launch_internal(self, device_name: str) -> None:
        args = [self._srv_binary, '-device', device_name, '-if', self._target_interface , '-endian',
                self._target_endian, '-vd', '-noir', '-timeout', '2000', '-singlerun', '-silent', '-speed',
                self._speed]
        if self._jlink_addr is not None:
            args.append('-select')
            args.append(f'IP={self._jlink_addr}')
        if self._serial_number is not None:
            if self._jlink_addr is not None:
                log.warning('JLink address and JLINK serial number given. Ignoring serial in favour of address.')
            else:
                args.append('-select')
                args.append(f'USB={self._serial_number}')
        if self._port is not None:
            args.append('-port')
            args.append(f'{self._port}')
        if self._jlink_script is not None:
            args.append('-scriptfile')
            args.append(self._jlink_script)
        if self._jlink_extconf is not None:
            args.extend(self._jlink_extconf.split())

        cflags = 0
        if platform.system() == 'Windows':
            cflags = subprocess.CREATE_NEW_PROCESS_GROUP
        self._srv_process = subprocess.Popen(args, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=cflags)

        p: psutil.Process = psutil.Process(self._srv_process.pid)
        startup_done = False
        try:
            # query the started process until it has opened a listening socket on the expected port
            end_time = time.time() + 8
            while startup_done is False and time.time() < end_time:
                for c in p.net_connections():
                    if c.laddr.port == self.port:
                        ip_ver: str = 'IPv6' if c.family == socket.AF_INET6 else 'IPv4'
                        jlink_ser_num: str = f' (JLINK SN: {self._serial_number}) ' if self._serial_number else ' '

                        log.info(f'GDB server{jlink_ser_num}is now listening on port {self.port} ({ip_ver})!')
                        startup_done = True

        except psutil.AccessDenied as ex:
            # On Linux the situation was observed that from newly launched GDB server processes
            # an AccessDenied exception is raised when accessing them with psutils. This exception
            # is then 'thrown' upwards where it is handled by retrying to create the process.
            raise ex

        except (NoSuchProcess, PermissionError) as ex:
            log.error('JLINK GDB server has terminated!')
            end_time = time.time() + 2
            res_poll = None
            while not startup_done and time.time() < end_time:
                res_poll = self._srv_process.poll()
                if res_poll is not None:
                    break
            if res_poll is not None:
                err_code, err_str = self._conv_jlink_error(self._srv_process.poll())
                log.error(f'J-Link gdb server termination reason: {err_code:x} ({err_str})')
                if err_code == -2:
                    log.error('Already a JLINK GDB server instance running?')
                if err_code == -5:
                    log.debug('GDB server command line:')
                    log.debug(' '.join(args))
            raise DottException('Startup of JLINK gdb server failed!') from None

        if not startup_done:
            raise DottException('Startup of JLINK gdb server failed due to timeout!') from None
        else:
            self._addr = '127.0.0.1'
            atexit.register(self.shutdown)

    def _launch(self, device_name: str):
        start_done: bool = False
        while not start_done:
            try:
                self._launch_internal(device_name)
                start_done = True
            except psutil.AccessDenied as ex:
                pass

    def shutdown(self):
        if self._srv_process is not None:
            # if the gdb server is still running (despite being started in single run mode) it is terminated here
            try:
                if platform.system() == 'Windows':
                    os.kill(self._srv_process.pid, signal.CTRL_BREAK_EVENT)
                else:
                    os.kill(self._srv_process.pid, signal.SIGINT)
                self._srv_process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                self._srv_process.terminate()
            self._srv_process = None

    def _conv_jlink_error(self, jlink_error: int) -> (int, str):
        bits_in_word = 32
        err_code = jlink_error - (1 << bits_in_word)

        err_str = 'Unknown error code.'
        if err_code == 0:
            err_str = 'No error. Gdb server closed normally.'
        if err_code == -1:
            err_str = 'Unknown error. Should not happen.'
        if err_code == -2:
            err_str = f'Failed to open listener port (default: 2331, current: {self.port}).'
        if err_code == -3:
            err_str = 'Could not connect to target. No target voltage detected or connection failed.'
        if err_code == -4:
            err_str = 'Failed to accept a connection from GDB.'
        if err_code == -5:
            err_str = 'Failed to parse the command line options, wrong or missing command line parameter.'
        if err_code == -6:
            err_str = 'Unknown or no device name set.'
        if err_code == -7:
            err_str = 'Failed to connect to J-Link.'

        return err_code, err_str


class GdbServerPEMicro(GdbServer):
    def __init__(self, gdb_svr_binary: str | None, addr: str | None, port: int, device_name: str,
                 pemicro_port: str | None, pemicro_interface: str | None, endian: str, dott_runtime_path: str | None):
        super().__init__(addr, port)
        self._srv_binary: str | None = gdb_svr_binary
        self._pemicro_port: str = pemicro_port
        self._pemicro_interface: str = pemicro_interface
        self._target_endian: str = endian
        self._srv_process = None
        # Popen.__del__ occasionally complains under Windows about invalid file handles on interpreter shutdown.
        # This is somewhat distracting and is silenced by a custom delete function.
        subprocess.Popen.__del_orig__ = subprocess.Popen.__del__
        subprocess.Popen.__del__ = GdbServerPEMicro._popen_del

        if not self._srv_binary and dott_runtime_path:
            # No PE Micro gdb server binary specified in config. Check if it is installed as part of DOTT runtime.
            if platform.system() == 'Windows':
                os_path: str = 'win32'
                bin_ext: str = '.exe'
            elif platform.system() == 'Linux':
                os_path: str = 'lin'
                bin_ext: str = ''
            else:
                raise DottException('Only Windows and Linux are currently supported for PE Micro environments.')
            self._srv_binary = f'{dott_runtime_path}{os.sep}apps{os.sep}pemicro{os.sep}{os_path}{os.sep}pegdbserver_console{bin_ext}'

        log.info(f'PE Micro GDB server binary:   {self._srv_binary}')
        if not os.path.exists(self._srv_binary):
            raise DottException(f'PE Micro gdb server binary could not be found ({self._srv_binary})!')

        if self.addr is None:
            self._launch(device_name)

    @staticmethod
    def _popen_del(instance):
        try:
            instance.__del_orig__()
        except:
            pass

    def _launch_internal(self, device_name: str) -> None:
        args = [self._srv_binary, f'-device={device_name}', f'-serverport={self.port}', '-singlesession', '-startserver']

        if self._pemicro_port is not None:
            args.append(f'-port={self._pemicro_port}')

        if self._pemicro_interface is not None:
            args.append(f'-interface={self._pemicro_interface}')

        cflags = 0
        if platform.system() == 'Windows':
            cflags = subprocess.CREATE_NEW_PROCESS_GROUP
        self._srv_process = subprocess.Popen(args, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=cflags)

        p = psutil.Process(self._srv_process.pid)
        try:
            # query the started process until it has opened a listening socket on the expected port
            startup_done = False
            end_time = time.time() + 8
            while startup_done is False and time.time() < end_time:
                for c in p.connections():
                    if c.laddr.port == self.port:
                        log.info(f'GDB server is now listening on port {self.port}!')
                        startup_done = True

        except psutil.AccessDenied as ex:
            # On Linux the situation was observed that from newly launched GDB server processes
            # an AccessDenied exception is raised when accessing them with psutils. This exception
            # is then 'thrown' upwards where it is handled by retrying to create the process.
            raise ex

        except (NoSuchProcess, PermissionError) as ex:
            log.error('PEMicro GDB server has terminated!')
            end_time = time.time() + 2
            startup_done: bool = False
            while not startup_done and time.time() < end_time:
                res_poll = self._srv_process.poll()
                if res_poll is not None:
                    break
            raise DottException('Startup of PEMicro gdb server failed!') from None

        if not startup_done:
            raise DottException('Startup of PEMicro gdb server failed due to timeout!') from None
        else:
            self._addr = '127.0.0.1'
            atexit.register(self.shutdown)

    def _launch(self, device_name: str):
        start_done: bool = False
        while not start_done:
            try:
                self._launch_internal(device_name)
                start_done = True
            except psutil.AccessDenied as ex:
                pass

    def shutdown(self):
        if self._srv_process is not None:
            # if the gdb server is still running (despite being started in single run mode) it is terminated here
            try:
                if platform.system() == 'Windows':
                    os.kill(self._srv_process.pid, signal.CTRL_BREAK_EVENT)
                else:
                    os.kill(self._srv_process.pid, signal.SIGINT)
                self._srv_process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                self._srv_process.terminate()
            self._srv_process = None


class GdbClient(object):

    # Create a new gdb instance
    # gdb_client_binary ... binary of gdb client (in PATH or with full-qualified path)
    # gdb_server_addr   ... gdb server address as supplied to GDB's target command (e.g., remote :2331);
    #                       if none DOTT tries to start a Segger GDB server instance and connect to it
    def __init__(self, gdb_client_binary: str) -> None:
        self._gdb_client_binary: str = gdb_client_binary
        self._mi_controller: GdbControllerDott | None = None
        self._gdb_mi: GdbMi | None = None

        # set Python Embedded (used for GDB commands) path such that gdb subprocess actually finds it
        my_env = os.environ.copy()
        python_emb_path = DottConf.get(DottConf.keys.dott_rt_python_emb_path)
        python_emb_pkg_path = DottConf.get(DottConf.keys.dott_rt_python_emb_packagepath)
        if python_emb_path is None:
            raise Exception(f'{DottConf.keys.dott_rt_python_emb_path} not set. Can not load gdb command support. Aborting.')
        if platform.system() == 'Windows':
            os.environ['PATH'] = f'{python_emb_path};{my_env["PATH"]}'
            os.environ['PYTHONPATH'] = '%s;%s\\lib;%s\\lib\\site-packages;%s\\DLLs' % ((python_emb_path,) * 4)
        else:
            os.environ['PYTHONPATH'] = f'{python_emb_path}:{python_emb_pkg_path}'
            ld_lib_path = f':{my_env["LD_LIBRARY_PATH"]}' if 'LD_LIBRARY_PATH' in my_env.keys() else ''
            os.environ['LD_LIBRARY_PATH'] = f'{python_emb_path}{ld_lib_path}'

        my_dir = os.path.dirname(os.path.realpath(__file__))
        os.environ['PYTHONPATH'] += os.pathsep + str(Path(my_dir + '/..'))

    # Create DB client instance.
    def create(self) -> None:
        # create 'GDB Machine Interface' instance and put it async mode
        self._mi_controller = GdbControllerDott([self._gdb_client_binary, "--nx", "--quiet", "--interpreter=mi3"])
        self._gdb_mi = GdbMi(self._mi_controller)

    @property
    def gdb_mi(self) -> GdbMi:
        return self._gdb_mi
