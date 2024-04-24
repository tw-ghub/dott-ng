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

from abc import ABC, abstractmethod

from dottmi.dott import dott
from dottmi.target import Target


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
        pass

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
