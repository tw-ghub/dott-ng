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
import pytest

from dottmi.dott import dott
from dottmi.dott_conf import DottConf, DottConfExt
from dottmi.dottexceptions import DottException


class TestTargetCreation:
    """
    These snippets illustrate different ways to create DOTT targets. A DOTT target essentially
    represents an MCU core.
    """

    def test_target_no_default(self):
        """
        This test shows how to skip the creation of the DOTT default target (dott().target) and how to create
        a target 'manually'.
        """
        # skip creation of default target
        d = dott(create_default_target=False)

        # there is no default target available. let's check!
        with pytest.raises(DottException):
            d.target.mem.read_uint32(0xE000ED00)

        # create custom target and set config options
        dconf = DottConfExt()
        dconf.set(DottConf.keys.monitor_type, 'jlink')
        dconf.set(DottConf.keys.device_name, 'stm32f072rb')
        dconf.parse_config()  # validates config settings and sets missing settings to defaults; must be called before
                              # passing config to create_target()
        t = d.create_target(dconf)
        cpuid: int = t.mem.read_uint32(0xE000ED00)
        assert cpuid == 0x410cc200

        # note: The first target that is created using create_target() is automatically set as default target.
        #       Hence, we now can use DOTT's default target and don't get an exception anymore.
        dott().target.mem.read_uint32(0xE000ED00)
        dott().target.log.debug(hex(cpuid))
        assert cpuid == 0x410cc200

    def test_target_multiple_no_default(self):
        """
        This test shows how to skip the creation of the DOTT default target (dott().target) and how to create
        a target 'manually'.
        """
        # skip creation of default target
        d = dott(create_default_target=False)

        # create 1st custom target and set config options
        dconf1 = DottConfExt()
        dconf1.set(DottConf.keys.monitor_type, 'jlink')
        dconf1.set(DottConf.keys.device_name, 'stm32f072rb')
        dconf1.parse_config(silent=False)  # parse_config output can also be silenced by setting silent=True
        t1 = d.create_target(dconf1)

        # create 2nd custom target and set config options
        dconf2 = DottConfExt()
        dconf2.set(DottConf.keys.monitor_type, 'jlink')
        dconf2.set(DottConf.keys.device_name, 'stm32f072rb')
        dconf2.parse_config(silent=False)
        t2 = d.create_target(dconf2)

        cpuid: int = t1.mem.read_uint32(0xE000ED00)
        t1.log.debug(hex(cpuid))
        assert cpuid == 0x410cc200
        t1.mem.write_uint32(0x20000000, 0xdeadbeef)

        cpuid: int = t2.mem.read_uint32(0xE000ED00)
        t2.log.debug(hex(cpuid))
        assert cpuid == 0x410cc200
        assert t2.mem.read_uint32(0x20000000) == 0xdeadbeef

        t1.disconnect()
        t2.disconnect()

    def test_default_target(self):
        """
        This test used the default target which is auto-created (based on settings from conftest.py and dott.ini)
        when calling dott() for the first time.
        """
        dt = dott().target
        cpuid: int = dt.mem.read_uint32(0xE000ED00)
        dt.log.debug(hex(cpuid))
        assert cpuid == 0x410cc200
        dott().shutdown()
