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

import time
from abc import ABC, abstractmethod

from dottmi.dott import dott
from dottmi.target import Target
from dottmi.utils import log


class RegBits:
    """
    Bitfield properties. Basically start and end within the register. The mask is computed from it.
    """
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end
        self.mask = (pow(2, end - start + 1) - 1)


class DeviceRegsDott(ABC):
    """
    DOTT-specific device based class.
    """
    def __init__(self, dt: Target | None = None):
        self._dt: Target = dt if dt else dott().target

    @property
    def target(self) -> Target:
        return self._dt


class RegBase(ABC):
    """
    Register base class. Providing (de-)serializing raw register content, monitor implementation and creation of
    string representation.
    """
    def __init__(self, reg_addr: int, reg_size: int):
        self._reg_addr: int = reg_addr
        self._reg_raw: int = 0x0
        self._reg_size: int = reg_size

    def _reg_bits_from_raw(self, rb: RegBits) -> int:
        return (self._reg_raw >> rb.start) & rb.mask

    def _reg_bits_to_raw(self, val: int, rb: RegBits) -> None:
        # clear val bits in raw and then set them to the new values
        self._reg_raw &= ~(rb.mask << rb.start)
        self._reg_raw |= ((val & rb.mask) << rb.start)

    def _reg_from_raw(self):
        for p in [prop for prop in dir(self) if prop.startswith('_bits_')]:
            self.__setattr__(p[6:], self._reg_bits_from_raw(self.__getattribute__(p)))

    def _reg_to_raw(self):
        for p in [prop for prop in dir(self) if prop.startswith('_bits_')]:
            self._reg_bits_to_raw(self.__getattribute__(p[6:]), self.__getattribute__(p))

    @abstractmethod
    def fetch(self):
        pass

    @abstractmethod
    def commit(self):
        pass

    @property
    def raw(self) -> int:
        self._reg_to_raw()
        return self._reg_raw

    @raw.setter
    def raw(self, raw: int) -> None:
        self._reg_raw = raw
        self._reg_from_raw()

    def __enter__(self):
        self.fetch()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.commit()

    def __str__(self) -> str:
        ret: str = ''
        for p in [prop for prop in dir(self) if prop.startswith('_bits_')]:
            val = self.__getattribute__(p[6:])
            ret += f' {p[6:]}: 0x{val:x}\n'
        return ret


class RegBaseDott(RegBase, ABC):
    """
    DOTT-specific register base class which implements fetch and commit using DOTT mem write.
    """
    def __init__(self, reg_addr: int, dev: DeviceRegsDott, reg_size: int = 32):
        super().__init__(reg_addr, reg_size)
        self._dev = dev

    def fetch(self):
        self._reg_raw = self._dev.target.mem.read_uint32(self._reg_addr)
        self._reg_from_raw()

    def commit(self):
        self._reg_to_raw()
        self._dev.target.mem.write_uint32(self._reg_addr, self._reg_raw)


"""
Register example classes - might be aut-generated from SVD or CMSIS header file.
"""


class RegCPUID(RegBaseDott):
    def __init__(self, reg_addr: int, dr: DeviceRegsDott) -> None:
        """
        Arm Cortex-M0 CPUID register
        https://developer.arm.com/documentation/dui0497/a/cortex-m0-peripherals/system-control-block/cpuid-register
        """
        super().__init__(reg_addr, dr)
        self.IMPLEMENTER: int = 0x0
        self._bits_IMPLEMENTER = RegBits(start=24, end=31)
        self.VARIANT: int = 0x0
        self._bits_VARIANT = RegBits(start=20, end=23)
        self.ARCHITECTURE: int = 0x0
        self._bits_ARCHITECTURE = RegBits(start=16, end=19)
        self.PARTNO: int = 0x0
        self._bits_PARTNO = RegBits(start=4, end=15)
        self.REVISION: int = 0x0
        self._bits_REVISION = RegBits(start=0, end=3)


class RegAIRCR(RegBaseDott):
    """
    Arm Cortex-M0 AICR register.
    https://developer.arm.com/documentation/dui0497/a/cortex-m0-peripherals/system-control-block/application-interrupt-and-reset-control-register
    """
    def __init__(self, reg_addr: int, dr: DeviceRegsDott) -> None:
        super().__init__(reg_addr, dr)
        self.VECTKEY: int = 0x0
        self._bits_VECTKEY = RegBits(start=16, end=31)
        self.ENDIANESS: int = 0x0
        self._bits_ENDIANESS = RegBits(start=15, end=15)
        self.SYSRESETREQ: int = 0x0
        self._bits_SYSRESETREQ = RegBits(start=2, end=2)
        self.VECTCLRACTIVE: int = 0x0
        self._bits_VECTCLRACTIVE = RegBits(start=1, end=1)


class MyDeviceRegs(DeviceRegsDott):
    def __init__(self, dt: Target = dott().target):
        super().__init__(dt)

        self.CPUID = RegCPUID(0xE000ED00, self)
        self.RegAIRC = RegAIRCR(0xE000ED0C, self)


"""
Usage examples.
"""


def test_cpuid():
    dt = dott().target
    stm32f072 = MyDeviceRegs(dt)

    stm32f072.CPUID.fetch()
    assert stm32f072.CPUID.raw == 0x410cc200
    assert stm32f072.CPUID.IMPLEMENTER == 0x41  # ARM
    assert stm32f072.CPUID.ARCHITECTURE == 0xc  # ARMv6-M
    assert stm32f072.CPUID.PARTNO == 0xc20  # Cortex-M0
    assert stm32f072.CPUID.REVISION == 0x0  # r0p0

    log.debug(f'\nCPUID\n{stm32f072.CPUID}')


def test_cpuid_monitor():
    dt = dott().target
    stm32f072 = MyDeviceRegs(dt)

    with stm32f072.CPUID as r:
        # note: fetch is done automatically when entering the monitor
        assert r.raw == 0x410cc200
        assert r.IMPLEMENTER == 0x41  # ARM
        assert r.ARCHITECTURE == 0xc  # ARMv6-M
        assert r.PARTNO == 0xc20  # Cortex-M0
        assert r.REVISION == 0x0  # r0p0

        log.debug(f'\nCPUID\n{r}')


def test_reset(target_load, target_reset):
    dt = dott().target
    dev = MyDeviceRegs(dt)

    dt.cont()
    time.sleep(1)
    dt.halt()

    # note: global_data is initialized to 0xdeadbeef in firmware and then gets incremented in main loop
    gd = dt.eval('global_data')
    assert gd > 0xdeadbeef

    dt.eval('global_data = 0x0')
    gd = dt.eval('global_data')
    assert gd == 0x0

    # Trigger reset by writing to AIRC.SYSRESETREQ (required to set VECTKEY as well)
    with dev.RegAIRC as r:
        # note: fetch done automatically
        r.VECTKEY = 0x05FA
        r.SYSRESETREQ = 0x1
    # note: commit done automatically

    # let target run and initialize
    dt.cont()
    time.sleep(1)
    dt.halt()

    # global_data is expected to have been initialized again to deadbeef and incremented from there
    gd = dt.eval('global_data')
    assert gd > 0xdeadbeef
