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

from __future__ import annotations  # available from Python 3.7 onwards, default from Python 3.11 onwards

import threading
import time
import typing

from dottmi.dott_conf import DottConf, DottConfExt
from dottmi.gdb import GdbServer

if typing.TYPE_CHECKING:
    from dottmi.target import Target

import types
from typing import List

from dottmi.dottexceptions import DottException
from dottmi.monitor import MonitorJLink, Monitor, MonitorOpenOCD, MonitorPEMicro
from dottmi.utils import log_setup, singleton, ExceptionPropagator, log


class DottHooks(object):
    _pre_connect_hook: types.FunctionType = None
    _gdb_pre_connect_hook: types.FunctionType = None

    @classmethod
    def set_pre_connect_hook(cls, pre_connect_hook: types.FunctionType) -> None:
        """
        This hook is called before the target instance is created. Neither a GDB server nor a GDB client instance exist at this point.

        Args:
            pre_connect_hook: Callback function.
        """
        cls._pre_connect_hook = pre_connect_hook

    @classmethod
    def exec_pre_connect_hook(cls) -> None:
        if cls._pre_connect_hook is not None:
            cls._pre_connect_hook()

    @classmethod
    def set_gdb_pre_connect_hook(cls, gdb_pre_connect_hook: types.FunctionType) -> None:
        """
        This hook is called after the GDB client process is instantiated but before the connection to the GDB server is established.
        This gives the possibility to adapt GDB client connection settings (e.g., "remotetimeout" or "tcp connect-timeout").

        Args:
            gdb_pre_connect_hook: Callback function.
        """
        cls._gdb_pre_connect_hook = gdb_pre_connect_hook

    @classmethod
    def exec_gdb_pre_connect_hook(cls, target: Target) -> None:
        if cls._gdb_pre_connect_hook is not None:
            cls._gdb_pre_connect_hook(target)


# ----------------------------------------------------------------------------------------------------------------------
@singleton
class Dott(object):

    def __init__(self, create_default_target: bool = True) -> None:
        """
        Initialize the DOTT framework. Note: This class is a singleton. Hence, repetitive attempts to instantiate this
        class will return the same singleton instance.

        For a single-core system, the default target is used to access the CPU. In a multicore environment, the default
        target can still be used for the primary CPU while targets for the other CPU cores can be created via the
        create_target() method based on a CPU-specific DOTT config. Alternatively also the creation of the default
        target can be skipped (see create_default_target argument). In this case all targets are created using
        create_target.

        Args:
            create_default_target: If True (default) the default target is generated automatically, otherwise this step
                                   is skipped. Not that setting this flag to true also slips the parsing of DottConf.
        """
        self._default_target = None
        self._all_targets: List = []

        # initialize logging subsystem
        log_setup()

        if create_default_target:
            # read and pre-process configuration file
            DottConf.parse_config()

            # Hook called before the first debugger connection is made when using the default target.
            DottHooks.exec_pre_connect_hook()

            self._default_target = self.create_target(DottConf())

        # Initialize exception propagator to enable forwarding of exceptions from sob threads to main thread.
        ExceptionPropagator.setup()

    def create_target(self, dconf: [DottConf | DottConfExt], set_as_default_if_none: bool = True) -> Target:
        """
        Creates and returns a target object according to the settings of the provided DottConf instance.
        If the Dott() singleton does not have a default target yet (default target is None), the newly created
        target is set as default target (can be omitted with set_as_default_as_none).

        Args:
            dconf: DottConf instance used to configure the target instance.
            set_as_default_if_none: Sets this target as default target if there is no default target yet.

        Returns:
            Target instance configured according to dconf.
        """
        from dottmi import target
        from dottmi.gdb import GdbClient

        monitor_type = dconf.get(DottConf.keys.monitor_type)

        if monitor_type == 'jlink':
            monitor: Monitor = MonitorJLink()
        elif monitor_type == 'openocd':
            monitor: Monitor = MonitorOpenOCD()
        elif monitor_type == 'pemicro':
            monitor: Monitor = MonitorPEMicro()
        elif monitor_type == 'custom':
            try:
                import importlib
                monitor_cls = getattr(importlib.import_module(dconf.get(DottConf.keys.monitor_module)), dconf.get(DottConf.keys.monitor_class))
                monitor: Monitor = monitor_cls()
            except:
                raise DottException(f'Failed to instantiate {dconf.get(DottConf.keys.monitor_module)}::{dconf.get(DottConf.keys.monitor_class)}') from None
        else:
            raise DottException(f'Unknown debug monitor type {dconf.get(DottConf.keys.monitor_type)}.')

        gdb_server: GdbServer = monitor.create_gdb_server(dconf)

        # start GDB client
        gdb_client = GdbClient(dconf.get(DottConf.keys.gdb_client_binary))
        gdb_client.create()

        try:
            # create target instance and set GDB server address
            target = target.Target(gdb_server, gdb_client, monitor, dconf)

        except TimeoutError:
            gdb_server.shutdown()
            raise DottException('Connection attempt to GDB server timed out. Either GDB server is not running or GDB server is slow.'
                                'In that case, try to increase DottConf[gdb_server_connect_timeout]') from None
        except Exception as ex:
            gdb_server.shutdown()
            raise ex

        # add target to list of created targets to enable proper cleanup on shutdown
        if target:
            self._all_targets.append(target)
            # If there is no default target yet, the new target is set as default (returned via target property)
            # Can be skipped by setting set_as_default_if_none=False.
            if not self._default_target and set_as_default_if_none:
                self._default_target = target
        return target

    @property
    def target(self) -> Target:
        """
        Returns the default target instances via the Dott singleton which is especially useful for single core systems.

        Returns:
            The default target instance.
        """
        if not self._default_target:
            raise DottException('No default target available!')
        return self._default_target

    @target.setter
    def target(self, target: Target) -> None:
        """
        Prevents setting (overriding) the default target for the Dott singleton. The default target is the one which
        was created as first target.

        Args:
            target: Target instance to be set as default target.

        Raises:
            DottException
        """
        raise DottException('Target can not be set directly.')

    def shutdown(self) -> None:
        """
        Calls the disconnect method of the default target and all other targets which were created via the create_target() method.
        """
        for t in self._all_targets:
            t.disconnect()
        self._all_targets = []


# ----------------------------------------------------------------------------------------------------------------------
# For backwards compatibility reasons the Dott() singleton can also be accessed via the all lowercase dott function.
def dott(create_default_target: bool = True) -> Dott:
    return Dott(create_default_target)
