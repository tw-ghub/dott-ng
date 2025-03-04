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

from dottmi.dott import DottConf
from dottmi.fixtures import target_load_flash, target_reset_flash, pytest_sessionfinish

# set binaries used for the tests in this folder (relative to main conftest file)
DottConf.conf[DottConf.keys.app_load_elf] = f'01_component_testing/target/build/dott_example_01/dott_example_01.bin.elf'
DottConf.conf[DottConf.keys.app_symbol_elf] = f'01_component_testing/target/build/dott_example_01/dott_example_01.elf'
DottConf.conf[DottConf.keys.on_target_mem_model] = 'NOALLOC'

# re-target target_reset/load fixtures
target_load = target_load_flash
target_reset = target_reset_flash


def pytest_configure(config):
    # register markers with pytest
    config.addinivalue_line("markers", "live_access: marker for tests which access the target while it is running")
    config.addinivalue_line("markers", "irq_testing: marker for tests which 'manually' "
                                       "generate interrupts for testing purposes")
