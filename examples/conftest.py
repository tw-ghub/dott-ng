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

import logging
import os
import socket

import pigpio

from dottmi.dott import dott
from dottmi.fixtures import dott_auto_func_cleanup, dott_auto_connect_and_disconnect, target_reset_common, pytest_collection_finish, pytest_configure

# set working directory to the folder which contains this conftest file
import pytest

from dottmi.dott import DottConf

os.chdir(os.path.dirname(os.path.realpath(__file__)))

# silence the debug output from matplotlib
logging.getLogger('matplotlib').setLevel(logging.WARNING)


def set_config_options() -> None:
    # machine-specific settings (selected based on hostname)
    hostname = socket.gethostname()

    # General options
    DottConf.set('jlink_script', 'test.jlinkscript')
    DottConf.set('jlink_extconf', '-log jlink_log.txt')

    if hostname.lower() == 'dott':
        # running on JENKINS node
        DottConf.set('pigpio_addr', 'rpidott02')  # PiGPIO daemon on RaspberryPI (rpidott02)
        DottConf.set('jlink_serial', '51014146')

    elif hostname.lower() == 'thunder':
        # development machine
        pass

#    elif hostname == 'YOUR_HOST_NAME':
#        DottConf.set('gdb_server_addr', 'WWW.XXX.YYY.ZZZ')  # only needed for a remote JLINK connected to RaspberryPI
#        DottConf.set('pigpio_addr', 'AAA.BBB.CCC.DDD')  # remote PiGPIO daemon on RaspberryPI


# set host-specific parameters
set_config_options()


class CommDev(object):
    def __init__(self, pi, dev):
        self.pi = pi
        self.dev = dev


@pytest.fixture(scope='function')
def i2c_comm() -> CommDev:
    """"
    This fixture is used by tests which need to communicate with the target device using I2C.
    It relies on a RaspberryPi running the gpio daemon.

    Returns:
        Return a CommDev instance.
    """
    dott().target.startup_delay = .05
    pi = pigpio.pi(DottConf.conf['pigpio_addr'])
    # open I2C bus 1, set I2C device slave address to 0x40
    dev = pi.i2c_open(1, 0x40)
    yield CommDev(pi, dev)
    dott().target.startup_delay = .0
    pi.i2c_close(dev)
    pi.stop()
