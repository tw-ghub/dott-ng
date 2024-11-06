# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2024 Thomas Winkler <thomas.winkler@gmail.com>
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
import sys

import dottmi.utils
from dottmi.utils import log
from dottmi.dott import dott
from dottmi.dott_conf import DottConf


def setup_logging():
    logging.basicConfig(level=logging.DEBUG)
    dottmi.utils.log_setup()
    ch = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s.%(msecs)03d [%(levelname)s] %(filename)s @%(lineno)d: %(message)s')
    ch.setFormatter(formatter)
    log.addHandler(ch)
    log.propagate = False


def setup_dott():
    # This is important: DottConf.parse_config() expects to find dott.ini in the current working directory (CWD).
    # Therefore, we change CWD to the folder which contains dott.ini. If no dott.ini is found in CWD DOTT silently
    # skips parsing dott.ini. As an alternative all required config fields can be set in code (as the ELF file below).
    # The no dott.ini is needed.
    os.chdir(f'{os.path.dirname(os.path.realpath(__file__))}/../..')

    setup_logging()
    DottConf.parse_config()
    DottConf.conf[DottConf.keys.app_load_elf] = f'01_component_testing/target/build/dott_example_01/dott_example_01.elf'
    DottConf.conf[DottConf.keys.app_symbol_elf] = DottConf.conf[DottConf.keys.app_load_elf]


def example_no_pytest():
    dt = dott().target
    dt.load(None, DottConf.get(DottConf.keys.app_symbol_elf), enable_flash=False)
    res = dt.eval('example_NoArgs()')
    assert (42 == res)


if __name__ == '__main__':
    setup_dott()
    example_no_pytest()
