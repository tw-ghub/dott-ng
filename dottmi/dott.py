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

from dottmi import utils
from dottmi.dott_conf import DottConf
from dottmi.gdb import GdbServer

if typing.TYPE_CHECKING:
    from dottmi.target import Target

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

        self._default_target = self.create_target(DottConf.conf['device_name'])

    def create_target(self, device_name: str) -> Target:
        from dottmi import target
        from dottmi.gdb import GdbClient

        if DottConf.get('monitor_type') == 'jlink':
            monitor: Monitor = MonitorJLink()
        elif DottConf.get('monitor_type') == 'openocd':
            monitor: Monitor = MonitorOpenOCD()
        else:
            raise DottException(f'Unknown debug monitor type {DottConf.get("monitor_type")}.')

        gdb_server: GdbServer = monitor.create_gdb_server(DottConf())

        # start GDB client
        gdb_client = GdbClient(DottConf.conf['gdb_client_binary'])
        gdb_client.connect()

        try:
            # create target instance and set GDB server address
            target = target.Target(gdb_server, gdb_client, monitor, device_name,  DottConf.get('device_endianess'), DottConf.get('gdb_server_connect_timeout'))

        except TimeoutError:
            gdb_client.disconnect()
            gdb_server.shutdown()
            raise DottException('Connection attempt to GDB server timed out. Either GDB server is not running or GDB server is slow.'
                                'In that case, try to increase DottConf[gdb_server_connect_timeout]') from None

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
