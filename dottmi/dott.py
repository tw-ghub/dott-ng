# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022-2023 Thomas Winkler <thomas.winkler@gmail.com>
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

from __future__ import annotations  # available from Python 3.7 onwards, default from Python 3.11 onwards

import typing

from dottmi.dott_conf import DottConf

if typing.TYPE_CHECKING:
    from dottmi.target import Target

import socket
import types
from typing import List

from dottmi.dottexceptions import DottException
from dottmi.monitor import MonitorJLink, Monitor, MonitorOpenOCD
from dottmi.utils import log_setup, singleton


class DottHooks(object):
    _pre_connect_hook: types.FunctionType = None

    @classmethod
    def set_pre_connect_hook(cls, pre_connect_hook: types.FunctionType) -> None:
        cls._pre_connect_hook = pre_connect_hook

    @classmethod
    def exec_pre_connect_hook(cls) -> None:
        if cls._pre_connect_hook is not None:
            cls._pre_connect_hook()

# ----------------------------------------------------------------------------------------------------------------------
@singleton
class Dott(object):

    def __init__(self) -> None:
        self._default_target = None
        self._all_targets: List = []

        # initialize logging subsystem
        log_setup()

        # read and pre-process configuration file
        DottConf.parse_config()

        # the port number used by the internal auto port discovery; discovery starts at config's gdb server port
        self._next_gdb_srv_port: int = int(DottConf.conf['gdb_server_port'])

        # Hook called before the first debugger connection is made
        DottHooks.exec_pre_connect_hook()

        self._default_target = self.create_target(DottConf.conf['device_name'], DottConf.conf['jlink_serial'])

    def _get_next_srv_port(self, srv_addr: str) -> int:
        """
        Find the next triplet of free ("bind-able") TCP ports on the given server IP address.
        Ports are automatically advanced until a free port triplet is found.

        Args:
            srv_addr: IP address of the server.
        Returns:
            Returns the first port number of the discovered, free port triplet.
        """
        port = self._next_gdb_srv_port
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
                # JLINK GDB server needs 3 free ports in a row
                break

            port += 1
            if port >= 65535:
                raise DottException(f'Unable do find three (consecutive) free ports for IP {srv_addr}!')

        self._next_gdb_srv_port = start_port + sequentially_free_ports
        if self._next_gdb_srv_port > 65500:
            self._next_gdb_srv_port = int(DottConf.conf['gdb_server_port'])
        return start_port

    def create_gdb_server(self, device_name: str, jlink_serial: str = None, srv_addr: str = None, srv_port: int = -1) -> 'GdbServer':
        """
        Factory method to create a new GDB server instance. The following parameters are defined via DottConfig:
        gdb_server_binary, jlink_interface, device_endianess, jlink_speed, and jlink_server_addr.

        Args:
            device_name: Device name as used by debug monitor to identify corresponding flash loader algorithm.
            jlink_serial: JLINK serial number (None when only a single JLINK is connected).
            srv_addr: Server address (None for default).
            srv_port: Port the server shall listen on (-1 for default).
        Returns:
            The created GdbServer instance.
        """
        from dottmi.gdb import GdbServerJLink

        if srv_port == -1:
            srv_port = int(DottConf.conf['gdb_server_port'])

        if srv_addr is None:
            srv_addr = DottConf.conf['gdb_server_addr']

        if srv_addr is None:
            # if gdb server is launched by DOTT, we determine the port ourselves
            srv_port = self._get_next_srv_port('127.0.0.1')

        gdb_server = GdbServerJLink(DottConf.conf['gdb_server_binary'],
                                    srv_addr,
                                    srv_port,
                                    device_name,
                                    DottConf.conf['jlink_interface'],
                                    DottConf.conf['device_endianess'],
                                    DottConf.conf['jlink_speed'],
                                    jlink_serial,
                                    DottConf.conf['jlink_server_addr'],
                                    DottConf.conf['jlink_script'],
                                    DottConf.conf['jlink_extconf'])

        return gdb_server

    def create_target(self, device_name: str, jlink_serial: str = None) -> Target:
        from dottmi import target
        from dottmi.gdb import GdbClient

        srv_addr = DottConf.conf['gdb_server_addr']

        gdb_server = self.create_gdb_server(device_name, jlink_serial, srv_addr=srv_addr)

        # start GDB client
        gdb_client = GdbClient(DottConf.conf['gdb_client_binary'])
        gdb_client.connect()

        if DottConf.get('monitor_type') == 'jlink':
            monitor: Monitor = MonitorJLink()
        elif DottConf.get('monitor_type') == 'openocd':
            monitor: Monitor = MonitorOpenOCD()
        else:
            raise DottException(f'Unknown debug monitor type {DottConf.get("monitor_type")}.')

        try:
            # create target instance and set GDB server address
            target = target.Target(gdb_server, gdb_client, monitor, device_name)

        except TimeoutError:
            gdb_client.disconnect()
            gdb_server.shutdown()
            target = None

        # add target to list of created targets to enable proper cleanup on shutdown
        if target:
            self._all_targets.append(target)
        return target

    @property
    def target(self) -> Target:
        return self._default_target

    @target.setter
    def target(self, target: object):
        raise ValueError('Target can not be set directly.')

    def shutdown(self) -> None:
        for t in self._all_targets:
            t.disconnect()
        self._all_targets = []


# ----------------------------------------------------------------------------------------------------------------------
# For backwards compatibility reasons the Dott() singleton can also be accessed via the all lowercase dott function.
def dott() -> Dott:
    return Dott()
