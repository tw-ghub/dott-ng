# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2023 Thomas Winkler <thomas.winkler@gmail.com>
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
        self._target = None

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
    def clear_all_breakpoints(self) -> None:
        pass

    @abc.abstractmethod
    def reset(self) -> None:
        pass

    @abc.abstractmethod
    def xpsr_name(self) -> str:
        pass


class MonitorJLink(Monitor):
    def set_flash_device(self, device_name: str) -> None:
        self.run_cmd(f'flash device {device_name}')

    def enable_flash_download(self, enable: bool) -> None:
        flag: int = 1 if enable else 0
        self.run_cmd(f'flash download={flag}')

    def enable_flash_breakpoints(self, enable: bool) -> None:
        flag: int = 1 if enable else 0
        self.run_cmd(f'flash breakpoints={flag}')

    def clear_all_breakpoints(self) -> None:
        self.run_cmd('clrbp')

    def reset(self) -> None:
        self.run_cmd('reset')

    def xpsr_name(self) -> str:
        return 'xpsr'


class MonitorOpenOCD(Monitor):
    def set_flash_device(self, device_name: str) -> None:
        # For OpenOCD the flash device name is ignored for now
        pass

    def enable_flash_download(self, enable: bool) -> None:
        flag: str = 'enable' if enable else 'disable'
        self.run_cmd(f'gdb_flash_program {flag}')

    def enable_flash_breakpoints(self, enable: bool) -> None:
        flag: str = 'enable' if enable else 'disable'
        self.run_cmd(f'gdb_memory_map {flag}')

    def clear_all_breakpoints(self) -> None:
        self.run_cmd('rbp all')

    def reset(self) -> None:
        self.run_cmd('reset halt')

    def xpsr_name(self) -> str:
        return 'xPSR'
