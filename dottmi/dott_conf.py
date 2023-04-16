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

from __future__ import annotations

import configparser
import glob
import os
import platform
import subprocess
import sys
from ctypes import CDLL
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import List, Tuple, Union

from dottmi.dottexceptions import DottException
from dottmi.target_mem import TargetMemModel
from dottmi.utils import log


# ----------------------------------------------------------------------------------------------------------------------
# DOTT configuration registry. Data is read in from dott ini file. Additional settings can be made via
# project specific conftest files.
class DottConfExt(object):

    def __init__(self, ini_file='dott.ini') -> None:
        self._conf = {}
        self._dott_runtime = None
        self._parsed = None
        self._dott_ini = ini_file
        self.conf = self

    def set(self, key: str, val: str) -> None:
        self._conf[key] = val

    def set_runtime_if_unset(self, dott_runtime_path: str) -> None:
        if not os.path.exists(dott_runtime_path):
            raise ValueError(f'Provided DOTT runtime path ({dott_runtime_path}) does not exist.')
        if os.environ.get('DOTTRUNTIME') is None:
            os.environ['DOTTRUNTIME'] = dott_runtime_path

    def get(self, key: str):
        return self._conf[key]

    def __getitem__(self, key) -> Union[int, str, None]:
        return self._conf[key]

    def __setitem__(self, key, value) -> None:
        self._conf[key] = value

    def _setup_runtime(self) -> None:
        self.set('DOTTRUNTIME', None)

        dott_runtime_path = sys.prefix + os.sep + 'dott_data'
        if os.path.exists(dott_runtime_path):
            runtime_version: str = 'unknown'
            with Path(dott_runtime_path + '/apps/version.txt').open() as f:
                line = f.readline()
                while line:
                    if 'version:' in line:
                        runtime_version = line.lstrip('version:').strip()
                        break
                    line = f.readline()
            os.environ['DOTTGDBPATH'] = str(Path(f'{dott_runtime_path}/apps/gdb/bin'))
            os.environ['PYTHONPATH27'] = str(Path(f'{dott_runtime_path}/apps/python27/python-2.7.13'))
            self.set('DOTTRUNTIME', f'{dott_runtime_path} (dott-runtime package)')
            self.set('DOTT_RUNTIME_VER', runtime_version)
            self.set('DOTTGDBPATH', str(Path(f'{dott_runtime_path}/apps/gdb/bin')))
            self.set('PYTHONPATH27', str(Path(f'{dott_runtime_path}/apps/python27/python-2.7.13')))

            # Linux: check if libpython2.7 and libnurses5 are installed. Windows: They are included in the DOTT runtime.
            if platform.system() == 'Linux':
                res = subprocess.run([str(Path(f'{dott_runtime_path}/apps/gdb/bin/arm-none-eabi-gdb-py')), '--version'],
                                     stdout=subprocess.PIPE)
                if res.returncode != 0:
                    raise DottException('Unable to start gdb client. This might be caused by missing dependencies.\n'
                                        'Make sure that libpython2.7 and libncurses5 are installed.')

        # If DOTTRUNTIME is set in the environment it overrides the integrated runtime in dott_data
        if os.environ.get('DOTTRUNTIME') is not None and os.environ.get('DOTTRUNTIME').strip() != '':
            dott_runtime_path = os.environ.get('DOTTRUNTIME')
            dott_runtime_path = dott_runtime_path.strip()
            self.set('DOTTRUNTIME', dott_runtime_path)

            if not os.path.exists(dott_runtime_path):
                raise ValueError(f'Provided DOTT runtime path ({dott_runtime_path}) does not exist.')
            try:
                self._dott_runtime = SourceFileLoader('dottruntime', dott_runtime_path + os.sep + 'dottruntime.py').load_module()
                self._dott_runtime.setup()
                self.set('DOTT_RUNTIME_VER', self._dott_runtime.DOTT_RUNTIME_VER)
            except Exception as ex:
                raise Exception('Error setting up DOTT runtime.')

        if self.get('DOTTRUNTIME') is None:
            raise Exception('Runtime components neither found in DOTT data path nor in DOTTRUNTIME folder.')

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
                    # Note: On Linux, Segger provides symlinks in the x86 folder to the 32bit version of the the
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
                log.warn(f'The J-Link software with the highest version (in {jlink_path}) has known '
                         f'issues related to SRAM download and STM32 MCUs. Please upgrade to at least v6.52d')
        else:
            raise DottException(f'JLink software (esp. {segger_lib_name}) not found in path {jlink_path}.')
        jlink_version = f'{str(jlink_version)[:1]}.{str(jlink_version)[1:3]}{chr(int(str(jlink_version)[-2:]) + 0x60)}'

        return jlink_path, segger_lib_name, jlink_version

    def parse_config(self, force_reparse: bool = False) -> None:
        if self._parsed and not force_reparse:
            return
        self._parsed = True

        # setup runtime environment
        self._setup_runtime()
        log.info(f'DOTT runtime:          {self.get("DOTTRUNTIME")}')
        log.info(f'DOTT runtime version:  {self.get("DOTT_RUNTIME_VER")}')

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

            # create an in-memory copy of the DOTT section of the init file
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

        if 'app_load_elf' not in self._conf:
            raise Exception(f'app_load_elf not set')
        if not os.path.exists(self._conf['app_load_elf']):
            raise ValueError(f'{self._conf["app_load_elf"]} does not exist.')
        log.info(f'APP ELF (load):        {self._conf["app_load_elf"]}')

        if 'app_symbol_elf' not in self._conf:
            # if no symbol file is specified assume that symbols are contained in the load file
            self._conf['app_symbol_elf'] = self._conf['app_load_elf']
        if not os.path.exists(self._conf['app_symbol_elf']):
            raise ValueError(f'{self._conf["app_symbol_elf"]} does not exist.')
        log.info(f'APP ELF (symbol):      {self._conf["app_symbol_elf"]}')

        if 'device_name' not in self._conf:
            self._conf["device_name"] = 'unknown'
        log.info(f'Device name:           {self._conf["device_name"]}')

        if 'device_endianess' not in self._conf:
            self._conf['device_endianess'] = 'little'
        else:
            if self._conf['device_endianess'] != 'little' and self._conf['device_endianess'] != 'big':
                raise ValueError(f'device_endianess in {dott_ini} should be either "little" or "big".')
        log.info(f'Device endianess:      {self._conf["device_endianess"]}')

        if 'monitor_type' not in self._conf:
            self._conf['monitor_type'] = 'jlink'
        else:
            self._conf['monitor_type'] = self._conf['monitor_type'].strip().lower()
            if self._conf['monitor_type'].strip().lower() not in ('jlink', 'openocd'):
                raise ValueError(f'Unknown monitor type (supported: "jlink", "openocd"')
        log.info(f'Selected monitor type: {self._conf["monitor_type"].upper()}')

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
            default_gdb = 'arm-none-eabi-gdb-py'
            self._conf['gdb_client_binary'] = str(Path(f'{os.environ["DOTTGDBPATH"]}/{default_gdb}'))
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
        log.info(f'GDB server port:       {self._conf["gdb_server_port"]}')

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
            elif os.path.exists(jlink_path):
                self._conf['gdb_server_binary'] = str(Path(f'{jlink_path}/{jlink_gdb_server_binary}'))
            else:
                # As a last option we check if the GDB server binary is in PATH
                try:
                    subprocess.check_call((jlink_gdb_server_binary, '-device'))
                except subprocess.CalledProcessError:
                    # Segger gdb server exists and responded with an error since no device was specified
                    self._conf['gdb_server_binary'] = jlink_gdb_server_binary
                except Exception as ex:
                    raise Exception(f'GDB server binary {jlink_gdb_server_binary} not found! Checked {self._dott_ini}, '
                                    'default location and PATH. Giving up.') from None
            log.info(f'GDB server binary:     {self._conf["gdb_server_binary"]}')
        else:
            log.info('GDB server assumed to be already running (not started by DOTT).')
            self._conf['gdb_server_binary'] = None

        default_mem_model: TargetMemModel = TargetMemModel.TESTHOOK
        if 'on_target_mem_model' not in self._conf:
            self._conf['on_target_mem_model'] = default_mem_model
        else:
            self._conf['on_target_mem_model'] = str(self._conf['on_target_mem_model']).upper()
            if self._conf['on_target_mem_model'] not in TargetMemModel.get_keys():
                log.warn(f'On-target memory model ({self._conf["on_target_mem_model"]}) from {self._dott_ini} is unknown. '
                         f'Falling back to default.')
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


# ----------------------------------------------------------------------------------------------------------------------
# Global, static DottConf that is used as default for single-target test environments. This was the standard way to
# configure DOTT prior to the introduction of the non-Static DottConfExt.
class DottConf(object):
    conf = DottConfExt()

    @staticmethod
    def set(key: str, val: str) -> None:
        DottConf.conf.set(key, val)

    @staticmethod
    def set_runtime_if_unset(dott_runtime_path: str) -> None:
        DottConf.conf.set_runtime_if_unset(dott_runtime_path)

    @staticmethod
    def get(key: str):
        return DottConf.conf.get(key)

    @staticmethod
    def parse_config(force_reparse: bool = False) -> None:
        return DottConf.conf.parse_config(force_reparse)
