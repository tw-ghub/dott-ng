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

from __future__ import annotations

import configparser
import glob
import os
import platform
import subprocess
import sys
from ctypes import CDLL
from pathlib import Path
from typing import List, Tuple, Union

from dottmi.dottexceptions import DottException
from dottmi.target_mem import TargetMemModel
from dottmi.utils import log


class DottConfExt(object):
    """
    This class represents a DOTT configuration. Most configuration parameters are used to configure target parameters.
    Hence, when creating a new target a DottConfExt instance needs to be provided as input.

    Creation of a DottConfExt instance is a two-step process: (1) key/value pairs can be set programmatically from
    Python code. (2) By calling the parse_config() method, an optional dott.ini is read from the current work
    directory (cwd). parse_config() fills in key/value pairs from the dott.ini and performs parameter validation.
    key/value pairs from dott.ini always have lower priority than key/value pairs programmatically set prior to
    calling parse_config().
    """

    def __init__(self, ini_file='dott.ini') -> None:
        """
        Constructor.

        Args:
            ini_file: Alternative name for DOTT ini file. Ini file is expected to be located in current work directory
            (or relative to it).
        """
        self._conf = {}
        self._dott_runtime = None
        self._dott_runtime_path: str | None = None
        self._parsed = None
        self._dott_ini = ini_file
        self.conf = self

        # check for DOTT runtime environment and parse runtime config
        self._setup_runtime()

    def set(self, key: str, val: str | None) -> None:
        """
        Set a key / value pair in the configuration object.

        Args:
            key: Key to set. Should be a key from DottConf.keys
            val: Value to be set for key.
        """
        self._conf[key] = val

    def get(self, key: str) -> str | int | None:
        """
        Returns the value for the given key.

        Args:
            key: A key which exists in the configuration object. Should be a key form DottConf.keys.

        Returns: The value for the given key or None if the key does not exist.
        """
        return self._conf[key] if key in self._conf.keys() else None

    def get_runtime_path(self) -> str | None:
        """
        Returns the path of the DOTT runtime as used by DOTT.
        """
        return self._dott_runtime_path

    def __getitem__(self, key) -> Union[int, str, None]:
        return self._conf[key]

    def __setitem__(self, key, value) -> None:
        self._conf[key] = value

    def _setup_runtime(self) -> None:
        self.set('dott_rt_id', None)

        dott_runtime_path = sys.prefix + os.sep + 'dott_data'
        if os.path.exists(dott_runtime_path):
            from dott_ng_runtime.dott_runtime import DottRuntime
            DottRuntime.setup_runtime()
            # Note: keys can not yet be used here as DottConf is not fully initialized.
            self.set('dott_rt_id', DottRuntime.IDENTIFIER)
            self.set('dott_rt_ver', DottRuntime.VERSION)
            self.set('dott_rt_gdb_path', DottRuntime.GDBPATH)
            self.set('dott_rt_gdb_client', DottRuntime.GDBCLIENT)
            self.set('dott_rt_python_emb_path', DottRuntime.PYTHON_EMB_PATH)
            self.set('dott_rt_python_emb_packagepath', DottRuntime.PYTHON_EMB_PACKAGEPATH)

        if self.get('dott_rt_id') is None:
            raise Exception('Runtime components not found in DOTT data path.')

        self._dott_runtime_path = dott_runtime_path

    def _get_jlink_path(self, segger_paths: List[str], segger_lib_name: str, jlink_gdb_server_binary: str) -> Tuple[str, str, str]:
        all_libs = {}

        for search_path in segger_paths:
            libs = glob.glob(os.path.join(search_path, '**', segger_lib_name), recursive=True)

            for lib in libs:
                try:
                    if not os.path.exists(f'{os.path.dirname(lib)}{os.path.sep}{jlink_gdb_server_binary}'):
                        # Skip dirs which contain a JLINK dll but no GDB server executable (e.g., Ozone install folders).
                        continue
                    clib = CDLL(lib)
                except OSError:
                    # Note: On Linux, Segger provides symlinks in the x86 folder to the 32bit version of the
                    # JLink library using the 64bit library name. Attempting to load this library on a 64bit system
                    # results in an exception.
                    continue
                ver = clib.JLINKARM_GetDLLVersion()
                all_libs[ver] = lib

        jlink_path: str = ''
        jlink_version: str = '0'
        if len(all_libs) > 0:
            jlink_version = (sorted(all_libs.keys())[-1:])[0]
            jlink_path = all_libs.get(jlink_version)
            jlink_path = os.path.dirname(jlink_path)

            #                       6.50   6.50b  6.52   6.52a  6.52b  6.52c
            known_issue_versions = (65000, 65020, 65200, 65210, 65220, 65230)
            if jlink_version in known_issue_versions:
                log.warning(f'The J-Link software with the highest version (in {jlink_path}) has known '
                            f'issues related to SRAM download and STM32 MCUs. Please upgrade to at least v6.52d')
        else:
            raise DottException(f'JLink software (esp. {segger_lib_name}) not found in path {jlink_path}.')
        jlink_version = f'{str(jlink_version)[:1]}.{str(jlink_version)[1:3]}{chr(int(str(jlink_version)[-2:]) + 0x60)}'

        return jlink_path, segger_lib_name, jlink_version

    def parse_config(self, force_reparse: bool = False, silent: bool = False) -> None:
        """
        This function parses the DOTT configuration from received via two sources: (1) Values already set
        programmatically in the DottConfExt instance. (2) dott.ini in current work directory (cwd). If this file exists
        it is read and parsed. If it does not exist, reading is skipped.
        Key/value pairs already present in DottConfExt from step (1) are not overwritten with values from step (2) even
        if they have identical keys. That is, key/value pairs set programmatically take precedence over values set in
        dott.ini.

        Args:
            force_reparse: Forces a re-parsing of the configuration. By default, parse_config returns immediately if
                           parsing has already been performed.
            silent: Turns off all output otherwise generated by parse_config.
        """
        if self._parsed and not force_reparse:
            return
        self._parsed = True

        # disable log propagation if requested by caller
        orig_log_propagate: bool = log.propagate
        if silent:
            log.propagate = False

        # print runtime environment
        log.info(f'DOTT runtime:          {self.get(DottConf.keys.dott_rt_id)}')
        log.info(f'DOTT runtime version:  {self.get(DottConf.keys.dott_rt_ver)}')

        # print working directory
        log.info(f'work directory:        {os.getcwd()}')

        # default ini file
        dott_section = 'DOTT'

        # JLINK gdb server
        if platform.system() == 'Linux':
            jlink_default_path = [str(Path('/opt/SEGGER'))]
            jlink_gdb_server_binary = 'JLinkGDBServerCLExe'
            jlink_lib_name = 'libjlinkarm.so'
        else:
            jlink_default_path = [str(Path('C:/Program Files (x86)/SEGGER')), str(Path('C:/Program Files/SEGGER'))]
            jlink_gdb_server_binary = 'JLinkGDBServerCL.exe'
            jlink_lib_name = 'JLink_x64.dll'

        # the DOTTJLINKPATH environment variable overrides the default location of the Segger JLink package
        if 'DOTTJLINKPATH' in os.environ.keys():
            log.info(f'Overriding default JLink path ({jlink_default_path}) with DOTTJLINKPATH ({os.environ["DOTTJLINKPATH"]})')
            jlink_default_path = [os.environ['DOTTJLINKPATH']]

        # if a dott.ini is found in the working directory then parse it
        if os.path.exists(os.getcwd() + os.sep + self._dott_ini):
            # read ini file
            ini = configparser.ConfigParser()
            ini.read(os.getcwd() + os.sep + self._dott_ini)

            if not ini.has_section(dott_section):
                raise Exception(f'Unable to find section DOTT in {self._dott_ini}')

            # create an in-memory copy of the DOTT section of the ini file
            conf_tmp = dict(ini[dott_section].items())

        else:
            log.info(f'No dott.ini found in working directory.')
            conf_tmp = {}

        # only copy items from ini to in-memory config which are not already present (i.e., set programmatically)
        for k, v in conf_tmp.items():
            if k not in self._conf.keys():
                self._conf[k] = v

        # Go through the individual config options and set reasonable defaults
        # where they are missing (or return an error)

        if 'bl_load_elf' not in self._conf:
            self._conf['bl_load_elf'] = None
        if self._conf['bl_load_elf'] is not None:
            if not os.path.exists(self._conf['bl_load_elf']):
                raise ValueError(f'{self._conf["bl_load_elf"]} does not exist.')
        log.info(f'BL ELF (load):         {self._conf["bl_load_elf"]}')

        if 'bl_symbol_elf' not in self._conf:
            # if no symbol file is specified assume that symbols are contained in the load file
            self._conf['bl_symbol_elf'] = self._conf['bl_load_elf']
        if self._conf['bl_symbol_elf'] is not None:
            if not os.path.exists(self._conf['bl_symbol_elf']):
                raise ValueError(f'{self._conf["bl_symbol_elf"]} does not exist.')
        log.info(f'BL ELF (symbol):       {self._conf["bl_symbol_elf"]}')

        if 'bl_symbol_addr' not in self._conf:
            self._conf['bl_symbol_addr'] = 0x0
        elif self._conf['bl_symbol_addr'].strip() == '':
            self._conf['bl_symbol_addr'] = 0x0
        else:
            self._conf['bl_symbol_addr'] = int(self._conf['bl_symbol_addr'], base=16)
        log.info(f'BL ADDR (symbol):      0x{self._conf["bl_symbol_addr"]:x}')

        if 'app_load_elf' in self._conf:
            if not os.path.exists(self._conf['app_load_elf']):
                raise ValueError(f'{self._conf["app_load_elf"]} does not exist.')
        else:
            self._conf["app_load_elf"] = None
        log.info(f'APP ELF (load):        {self._conf["app_load_elf"]}')

        if 'app_symbol_elf' not in self._conf:
            # if no symbol file is specified assume that symbols are contained in the load file
            self._conf['app_symbol_elf'] = self._conf['app_load_elf']
        if self._conf['app_symbol_elf'] is not None and not os.path.exists(self._conf['app_symbol_elf']):
            raise ValueError(f'{self._conf["app_symbol_elf"]} does not exist.')
        log.info(f'APP ELF (symbol):      {self._conf["app_symbol_elf"]}')

        if 'device_name' not in self._conf:
            self._conf["device_name"] = 'unknown'
        log.info(f'Device name:           {self._conf["device_name"]}')

        if 'device_endianess' not in self._conf:
            self._conf['device_endianess'] = 'little'
        else:
            if self._conf['device_endianess'] != 'little' and self._conf['device_endianess'] != 'big':
                raise ValueError(f'device_endianess should be either "little" or "big".')
        log.info(f'Device endianess:      {self._conf["device_endianess"]}')

        _custom_monitor_info: str = ''
        if 'monitor_type' not in self._conf:
            self._conf['monitor_type'] = 'jlink'
        else:
            if self._conf['monitor_type'].strip().lower() not in ('jlink', 'openocd', 'pemicro'):

                # Check if monitor type is of format my.module.path.MyMonitorClass; if yes populate monitor_module
                # and monitor_class config values. In this case, monitor_type is set to 'custom'.
                if '.' in self._conf['monitor_type'].strip():
                    _custom_monitor_info = f" [{self._conf['monitor_type'].strip()}]"
                    parts = self._conf['monitor_type'].split('.')
                    if len(parts) > 0:
                        self._conf['monitor_class'] = parts[-1]
                    if len(parts) > 1:
                        self._conf['monitor_module'] = '.'.join(parts[0:-1])
                    else:
                        self._conf['monitor_module'] = None
                    self._conf['monitor_type'] = 'custom'

                else:
                    raise ValueError(f'Unknown monitor type (supported: "jlink", "openocd", "pemicro" or "my.module.path.MyMonitorClass"')

        log.info(f'Selected monitor type: {self._conf["monitor_type"].upper()} {_custom_monitor_info}')

        if self._conf[DottConf.keys.monitor_type] == 'jlink':
            # determine J-Link path and version
            jlink_path, jlink_lib_name, jlink_version = self._get_jlink_path(jlink_default_path, jlink_lib_name, jlink_gdb_server_binary)
            self._conf["jlink_path"] = jlink_path
            self._conf["jlink_lib_name"] = jlink_lib_name
            self._conf["jlink_version"] = jlink_version
            log.info(f'J-LINK local path:     {self._conf["jlink_path"]}')
            log.info(f'J-LINK local version:  {self._conf["jlink_version"]}')

            # We are connecting to a J-LINK gdb server which was not started by DOTT. Therefore, it does not make sense
            # to print, e.g., SWD connection parameters.
            if 'jlink_interface' not in self._conf:
                self._conf['jlink_interface'] = 'SWD'
            log.info(f'J-LINK interface:      {self._conf["jlink_interface"]}')

            if 'jlink_speed' not in self._conf:
                self._conf['jlink_speed'] = '15000'
            log.info(f'J-LINK speed (set):    {self._conf["jlink_speed"]}')

            if 'jlink_serial' not in self._conf:
                self._conf['jlink_serial'] = None
            elif self._conf['jlink_serial'] is not None and self._conf['jlink_serial'].strip() == '':
                self._conf['jlink_serial'] = None
            if self._conf['jlink_serial'] is not None:
                log.info(f'J-LINK serial:         {self._conf["jlink_serial"]}')

            if 'jlink_script' not in self._conf:
                self._conf['jlink_script'] = None
            if self._conf['jlink_script'] is not None:
                log.info(f'J-LINK script:         {self._conf["jlink_script"]}')

            if 'jlink_extconf' not in self._conf:
                self._conf['jlink_extconf'] = None
            if self._conf['jlink_extconf'] is not None:
                log.info(f'J-LINK extra config:   {self._conf["jlink_extconf"]}')

        if 'gdb_client_binary' not in self._conf:
            self._conf['gdb_client_binary'] = self._conf[DottConf.keys.dott_rt_gdb_client]
        log.info(f'GDB client binary:     {self._conf["gdb_client_binary"]}')

        if 'gdb_server_addr' not in self._conf:
            self._conf['gdb_server_addr'] = None
        elif self._conf['gdb_server_addr'].strip() == '':
            self._conf['gdb_server_addr'] = None
        else:
            self._conf['gdb_server_addr'] = self._conf['gdb_server_addr'].strip()
        log.info(f'GDB server address:    {self._conf["gdb_server_addr"]}')

        if 'gdb_server_port' not in self._conf or self._conf['gdb_server_port'] is None:
            self._conf['gdb_server_port'] = '2331'
        elif self._conf['gdb_server_port'].strip() == '':
            self._conf['gdb_server_port'] = '2331'
        log.info(f'GDB server port (std): {self._conf["gdb_server_port"]}')

        if 'gdb_server_connect_timeout' not in self._conf or self._conf['gdb_server_connect_timeout'] is None:
            self._conf['gdb_server_connect_timeout'] = '5'
        elif self._conf['gdb_server_connect_timeout'].strip() == '':
            self._conf['gdb_server_connect_timeout'] = '5'

        if 'fixture_timeout' not in self._conf or self._conf['fixture_timeout'] is None:
            self._conf['fixture_timeout'] = '5'
        elif self._conf['fixture_timeout'].strip() == '':
            self._conf['fixture_timeout'] = '5'

        if 'jlink_server_addr' not in self._conf or self._conf['jlink_server_addr'] is None:
            self._conf['jlink_server_addr'] = None
        elif self._conf['jlink_server_addr'].strip() == '':
            self._conf['jlink_server_addr'] = None
        if self._conf["jlink_server_addr"] is not None:
            log.info(f'JLINK server address:  {self._conf["jlink_server_addr"]}')

        if 'jlink_server_port' not in self._conf or self._conf['jlink_server_port'] is None:
            self._conf['jlink_server_port'] = '19020'
        elif self._conf['jlink_server_port'].strip() == '':
            self._conf['jlink_server_port'] = '19020'
        if self._conf["jlink_server_port"] != '19020':
            log.info(f'JLINK server port:     {self._conf["jlink_server_port"]}')
        if self._conf['gdb_server_addr'] is None:
            # no (remote) GDB server address given. try to find a local GDB server binary to launch instead

            if 'gdb_server_binary' in self._conf:
                if not os.path.exists(self._conf['gdb_server_binary']):
                    raise Exception(f'GDB server binary {self._conf["gdb_server_binary"]} ({self._dott_ini}) not found!')
            elif self._conf[DottConf.keys.monitor_type] == 'jlink' and os.path.exists(jlink_path):
                self._conf['gdb_server_binary'] = str(Path(f'{jlink_path}/{jlink_gdb_server_binary}'))
            elif self._conf[DottConf.keys.monitor_type] == 'jlink':
                # As a last option we check if the GDB server binary is in PATH
                try:
                    subprocess.check_call((jlink_gdb_server_binary, '-device'))
                except subprocess.CalledProcessError:
                    # Segger gdb server exists and responded with an error since no device was specified
                    self._conf['gdb_server_binary'] = jlink_gdb_server_binary
                except Exception as ex:
                    raise Exception(f'GDB server binary {jlink_gdb_server_binary} not found! Checked {self._dott_ini}, '
                                    'default location and PATH. Giving up.') from None
            else:
                self._conf['gdb_server_binary'] = None

            gdb_srv_bin = self._conf['gdb_server_binary'] if self._conf['gdb_server_binary'] else 'undefined'
            log.info(f'GDB server binary:     {gdb_srv_bin}')
        else:
            log.info('GDB server assumed to be already running (not started by DOTT).')
            self._conf['gdb_server_binary'] = None

        default_mem_model: TargetMemModel = TargetMemModel.TESTHOOK
        if 'on_target_mem_model' not in self._conf:
            self._conf['on_target_mem_model'] = default_mem_model
        else:
            self._conf['on_target_mem_model'] = str(self._conf['on_target_mem_model']).upper()
            if self._conf['on_target_mem_model'] not in TargetMemModel.get_keys():
                log.warning(f'On-target memory model ({self._conf["on_target_mem_model"]}) from {self._dott_ini} is '
                            f'unknown. Falling back to default.')
                self._conf['on_target_mem_model'] = default_mem_model
            else:
                self._conf['on_target_mem_model'] = TargetMemModel[self._conf['on_target_mem_model']]

        on_target_mem_prestack_alloc_size: int = 256
        if 'on_target_mem_prestack_alloc_size' in self._conf:
            if str(self._conf['on_target_mem_prestack_alloc_size']).strip() != '':
                on_target_mem_prestack_alloc_size = int(self._conf['on_target_mem_prestack_alloc_size'])
        self._conf['on_target_mem_prestack_alloc_size'] = on_target_mem_prestack_alloc_size

        on_target_mem_prestack_alloc_location: str = 'Reset_Handler'
        if 'on_target_mem_prestack_alloc_location' in self._conf:
            if str(self._conf['on_target_mem_prestack_alloc_location']).strip() != '':
                on_target_mem_prestack_alloc_location = str(self._conf['on_target_mem_prestack_alloc_location'])
        self._conf['on_target_mem_prestack_alloc_location'] = on_target_mem_prestack_alloc_location

        on_target_mem_prestack_halt_location: str = 'main'
        if 'on_target_mem_prestack_halt_location' in self._conf:
            if str(self._conf['on_target_mem_prestack_halt_location']).strip() != '':
                on_target_mem_prestack_halt_location = str(self._conf['on_target_mem_prestack_halt_location'])
        self._conf['on_target_mem_prestack_halt_location'] = on_target_mem_prestack_halt_location

        on_target_mem_prestack_total_stack_size: int = 0
        if 'on_target_mem_prestack_total_stack_size' in self._conf:
            if str(self._conf['on_target_mem_prestack_total_stack_size']).strip() != '':
                on_target_mem_prestack_total_stack_size = int(self._conf['on_target_mem_prestack_total_stack_size'])
        self._conf['on_target_mem_prestack_total_stack_size'] = on_target_mem_prestack_total_stack_size

        if self._conf['on_target_mem_model'] == TargetMemModel.PRESTACK:
            log.info(f'Std. target mem model for DOTT default fixtures:  {self._conf["on_target_mem_model"]} '
                     f'({on_target_mem_prestack_alloc_size}bytes '
                     f'@{on_target_mem_prestack_alloc_location}; '
                     f'halt @{on_target_mem_prestack_halt_location}; '
                     f'total stack: {on_target_mem_prestack_total_stack_size if on_target_mem_prestack_total_stack_size is not None else "unknown"})')
        else:
            log.info(f'Std. target mem model for DOTT default fixtures:  {self._conf["on_target_mem_model"]}')

        # restore log propagation to previous state if silent was requested
        if silent:
            log.propagate = orig_log_propagate


# ----------------------------------------------------------------------------------------------------------------------
class DottConf(object):
    """
    Global, static DottConf that is used as default for single-target test environments. This was the standard way to
    configure DOTT prior to the introduction of the non-static DottConfExt.
    """
    conf = DottConfExt()

    class keys(object):
        # GDB server connection parameters
        gdb_client_binary: str = 'gdb_client_binary'
        gdb_server_addr: str = 'gdb_server_addr'
        gdb_server_port: str = 'gdb_server_port'
        gdb_server_binary: str = 'gdb_server_binary'
        gdb_server_connect_timeout: str = 'gdb_server_connect_timeout'

        # Debug monitor variants
        monitor_type: str = 'monitor_type'
        monitor_module: str = 'monitor_module'
        monitor_class: str = 'monitor_class'

        # Device properties
        device_name: str = 'device_name'
        device_endianess: str = 'device_endianess'

        # JLINK-specific settings
        jlink_interface: str = 'jlink_interface'
        jlink_speed: str = 'jlink_speed'
        jlink_serial: str = 'jlink_serial'
        jlink_server_addr: str = 'jlink_server_addr'
        jlink_server_port: str = 'jlink_server_port'
        jlink_script: str = 'jlink_script'
        jlink_extconf: str = 'jlink_extconf'

        # PEMicro-specific settings
        pemicro_port: str = 'pemicro_port'
        pemicro_interface: str = 'pemicro_interface'

        # Application related settings
        bl_symbol_elf: str = 'bl_symbol_elf'
        bl_load_elf: str = 'bl_load_elf'
        bl_symbol_addr: str = 'bl_symbol_addr'
        app_load_elf: str = 'app_load_elf'
        app_symbol_elf: str = 'app_symbol_elf'

        # Memory allocation configuraiton
        on_target_mem_model: str = 'on_target_mem_model'
        on_target_mem_prestack_alloc_size: str = 'on_target_mem_prestack_alloc_size'
        on_target_mem_prestack_alloc_location: str = 'on_target_mem_prestack_alloc_location'
        on_target_mem_prestack_halt_location: str = 'on_target_mem_prestack_halt_location'
        on_target_mem_prestack_total_stack_size: str = 'on_target_mem_prestack_total_stack_size'

        # Timeout settings
        fixture_timeout: str = 'fixture_timeout'

        # DOTT runtime
        dott_rt_id: str = 'dott_rt_id'
        dott_rt_ver: str = 'dott_rt_ver'
        dott_rt_gdb_path: str = 'dott_rt_gdb_path'
        dott_rt_gdb_client: str = 'dott_rt_gdb_client'
        dott_rt_python_emb_path = 'dott_rt_python_emb_path'
        dott_rt_python_emb_packagepath = 'dott_rt_python_emb_packagepath'

    @staticmethod
    def set(key: str, val: str) -> None:
        """See get method in :func:`DottConfExt.set`."""
        DottConf.conf.set(key, val)

    @staticmethod
    def get(key: str):
        """See get method in :func:`DottConfExt.get`."""
        return DottConf.conf.get(key)

    @staticmethod
    def get_runtime_path() -> str | None:
        """See get method in :func:`DottConfExt.get_runtime_path`."""
        return DottConf.conf.get_runtime_path()

    @staticmethod
    def parse_config(force_reparse: bool = False) -> None:
        """See get method in :func:`DottConfExt.get_runtime_path`."""
        return DottConf.conf.parse_config(force_reparse)

    @staticmethod
    def log(key, val):
        """
        Logs key value pairs and indents values to a pre-defined (fixed) level.
        """
        key += ':'
        log.info(f'{key:25} {val}')
