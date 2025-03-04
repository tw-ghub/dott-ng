# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2023-2025 Thomas Winkler <thomas.winkler@gmail.com>
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

import abc
import typing

from dottmi import utils
from dottmi.dott_conf import DottConf, DottConfExt
from dottmi.gdb import GdbServer, GdbServerExternal, GdbServerJLink, GdbServerPEMicro
from dottmi.pylinkdott import TargetDirect

if typing.TYPE_CHECKING:
    from dottmi.target import Target

from dottmi.dottexceptions import DottException


class Monitor(abc.ABC):
    """
    This is a base implementation to abstract the debug monitor as, e.g., implemented in JLink GDB server, OpenOcd etc.
    The individual debug monitors are vendor-specific. By abstraction the monitor implementation, the upper layers can
    be implemented in a generic way.
    """
    def __init__(self):
        self._target: Target | None = None

    def set_target(self, target: Target):
        self._target = target

    def run_cmd(self, monitor_cmd: str) -> None:
        if not self._target:
            raise DottException('No target set for debug monitor. Can not execute monitor commands!')
        self._target.cli_exec(f'monitor {monitor_cmd}')

    @abc.abstractmethod
    def set_flash_device(self, device_name: str) -> None:
        pass

    @abc.abstractmethod
    def enable_flash_download(self, enable: bool) -> None:
        pass

    @abc.abstractmethod
    def enable_flash_breakpoints(self, enable: bool) -> None:
        pass

    @abc.abstractmethod
    def erase_flash(self) -> None:
        pass

    @abc.abstractmethod
    def clear_all_breakpoints(self) -> None:
        pass

    @abc.abstractmethod
    def reset(self) -> None:
        pass

    @abc.abstractmethod
    def xpsr_name(self) -> str:
        pass

    @abc.abstractmethod
    def _instantiate_gdb_server(self, dconf: [DottConf | DottConfExt]):
        pass

    @property
    def direct(self) -> TargetDirect:
        """
        This property provides direct access to the debug monitor. It bypassed GDB (and hence DOTT) entirely.
        CAUTION: Bypassing GDB implies that GDB (and hence DOTT) might get out of sync with target state! Therefore,
        use this feature with care! Accessing features of the debug monitor (probe) which are not supported by
        GDB directly is considered save (e.g., additional GPIO pins of the probe). Also, reading target memory is
        considered safe.
        However, writing and hence altering target state via this path may lead to out of sync states.
        Also, be aware that this type of direct access implementation is debug monitor (probe) specific and hence is
        not portable across different debug monitor (probe) environments!
        """
        raise NotImplementedError('This monitor implementation does not implement direct access.')

    def cleanup(self):
        """
        Perform whatever cleanup is required by the monitor implementation (if any).
        """
        pass

    def create_gdb_server(self, dconf: [DottConf | DottConfExt]) -> GdbServer:
        """
        Create new GDB server instance. If the configuration contains a gdb server address it is assumed that a GDB server is already running at this
        address and no attempt is made to launch a GDB server instance. Otherwise, it is tried to launch a gdb server instance corresponding to the
        monitor type.

        Args:
            dconf: Dott configuration database.

        Returns: GDB server instance.
        """
        addr = dconf.get(DottConf.keys.gdb_server_addr)
        port = dconf.get(DottConf.keys.gdb_server_port)
        if addr is not None:
            return GdbServerExternal(addr, port)
        else:
            return self._instantiate_gdb_server(dconf)


class MonitorJLink(Monitor):

    def __init__(self):
        super().__init__()
        self._direct: TargetDirect | None = None

    def _instantiate_gdb_server(self, dconf: [DottConf | DottConfExt]):
        srv_addr = dconf.get(DottConf.keys.gdb_server_addr)

        if srv_addr is not None:
            srv_port = dconf.get(DottConf.keys.gdb_server_port)
        else:
            # if gdb server is launched by DOTT, we determine the port ourselves
            srv_port = utils.Network.get_next_srv_port('127.0.0.1')

        return GdbServerJLink(
            dconf.get(DottConf.keys.gdb_server_binary),
            srv_addr,
            srv_port,
            dconf.get(DottConf.keys.device_name),
            dconf.get(DottConf.keys.jlink_interface),
            dconf.get(DottConf.keys.device_endianess),
            dconf.get(DottConf.keys.jlink_speed),
            dconf.get(DottConf.keys.jlink_serial),
            dconf.get(DottConf.keys.jlink_server_addr),
            dconf.get(DottConf.keys.jlink_script),
            dconf.get(DottConf.keys.jlink_extconf)
        )

    def set_flash_device(self, device_name: str) -> None:
        self.run_cmd(f'flash device {device_name}')

    def enable_flash_download(self, enable: bool) -> None:
        flag: int = 1 if enable else 0
        self.run_cmd(f'flash download={flag}')

    def enable_flash_breakpoints(self, enable: bool) -> None:
        flag: int = 1 if enable else 0
        self.run_cmd(f'flash breakpoints={flag}')

    def erase_flash(self) -> None:
        self.run_cmd('flash erase')

    def clear_all_breakpoints(self) -> None:
        self.run_cmd('clrbp')

    def reset(self) -> None:
        self.run_cmd('reset')

    def xpsr_name(self) -> str:
        return 'xpsr'

    @property
    def direct(self) -> TargetDirect:
        if not self._direct:
            # Create TargetDirect upon first access
            jlink_server_addr: str = self._target.dconf.get(DottConf.keys.jlink_server_addr)
            jlink_server_port: str = self._target.dconf.get(DottConf.keys.jlink_server_addr)
            jlink_serial: str = self._target.dconf.get(DottConf.keys.jlink_serial)
            device_name: str = self._target.dconf.get(DottConf.keys.device_name)
            self._direct = TargetDirect(jlink_server_addr, jlink_server_port, jlink_serial, device_name)

        return self._direct

    def cleanup(self):
        if self._direct:
            self._direct.disconnect()
            self._direct = None


class MonitorOpenOCD(Monitor):
    def _instantiate_gdb_server(self, dconf: [DottConf | DottConfExt]):
        raise NotImplementedError('Automatic starting of OpenOCD GDB server is not supported. Provide "gdb_server_addr" and "gdb_server_addr" '
                                  'config parameters to connect to an externally started/remote GDB server instance.')

    def set_flash_device(self, device_name: str) -> None:
        # For OpenOCD the flash device name is ignored for now
        pass

    def enable_flash_download(self, enable: bool) -> None:
        flag: str = 'enable' if enable else 'disable'
        self.run_cmd(f'gdb_flash_program {flag}')

    def enable_flash_breakpoints(self, enable: bool) -> None:
        flag: str = 'enable' if enable else 'disable'
        self.run_cmd(f'gdb_memory_map {flag}')

    def erase_flash(self) -> None:
        raise NotImplementedError('OpenOCD monitor currently does not support FLASH erase.')

    def clear_all_breakpoints(self) -> None:
        self.run_cmd('rbp all')

    def reset(self) -> None:
        self.run_cmd('reset halt')

    def xpsr_name(self) -> str:
        return 'xPSR'


class MonitorPEMicro(Monitor):
    def _instantiate_gdb_server(self, dconf: DottConf | DottConfExt):
        srv_addr = dconf.get(DottConf.keys.gdb_server_addr)

        if srv_addr is not None:
            srv_port = dconf.get(DottConf.keys.gdb_server_port)
        else:
            # if gdb server is launched by DOTT, we determine the port ourselves
            srv_port = utils.Network.get_next_srv_port('127.0.0.1')

        return GdbServerPEMicro(dconf.get(DottConf.keys.gdb_server_binary),
                                dconf.get(DottConf.keys.gdb_server_addr),
                                srv_port,
                                dconf.get(DottConf.keys.device_name),
                                dconf.get(DottConf.keys.pemicro_port),
                                dconf.get(DottConf.keys.pemicro_interface),
                                dconf.get(DottConf.keys.device_endianess),
                                dconf.get_runtime_path())

    def set_flash_device(self, device_name: str) -> None:
        # Unused for PE Micro (set when starting GDB server).
        pass

    def enable_flash_download(self, enable: bool) -> None:
        # No such option known for PE Micro (monitor commands are not officially documented).
        pass

    def enable_flash_breakpoints(self, enable: bool) -> None:
        # No such option known for PE Micro (monitor commands are not officially documented).
        pass

    def erase_flash(self) -> None:
        # No such option known for PE Micro (monitor commands are not officially documented).
        pass

    def clear_all_breakpoints(self) -> None:
        # No such option known for PE Micro (monitor commands are not officially documented).
        pass

    def reset(self) -> None:
        self.run_cmd('_reset')

    def xpsr_name(self) -> str:
        return 'xpsr'
