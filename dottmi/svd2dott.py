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

import argparse
import inspect
import os
import textwrap as tw
from os.path import basename
from typing import List, Tuple, TextIO

import lxml.etree

import dottmi.utils as du


class SVD2Dott:
    """
    This class implements a converter from Arm's CMSIS SVD (system view description) file
    format to a Python representation that then be used directly with the DOTT framework.
    """
    def __init__(self, svd_file: str, out_file: str, device_name: str | None = None,
                 newline: str = '\n', reg_prefix: str | None = None) -> None:
        self._device_name: str | None = device_name
        self._device_regs: List[Tuple[str, int]] = []
        self._license_text: str | None = None
        self._newline = newline
        self._out_file: str = out_file
        self._reg_prefix: str = reg_prefix if reg_prefix else ''
        self._svd_xml = lxml.etree.parse(svd_file)

    @staticmethod
    def _get_node_text(xml, name: str) -> str:
        nodes = xml.xpath(name)
        if len(nodes) != 1:
            raise ValueError(f'Exactly 1 node expected for name {name}. Found {len(nodes)} nodes.')
        return str(nodes[0].text).strip()

    def _emit_device_registers(self, f: TextIO) -> None:

        f.write(tw.dedent(f'''
            class {self._device_name}Registers(DeviceRegsDott):
                """
                This class defines all registers together with their address of device {self._device_name}.
                """

                def __init__(self, dt: Target | None = None) -> None:
                    super().__init__(dt)
        '''))

        for reg, addr in self._device_regs:
            f.write(tw.indent(f'self.{reg} = Reg{reg}({hex(addr)}, self){self._newline}', ' '*8))

    def _emit_regbits(self, f: TextIO, xml_register) -> None:
        for regbits in xml_register.xpath("./fields/field"):
            name: str = self._get_node_text(regbits, "name")
            msb: str = self._get_node_text(regbits, 'msb')
            lsb: str = self._get_node_text(regbits, 'lsb')

            f.write(tw.indent(tw.dedent(f"""
                self.{name}: int = 0x0
                self._bits_{name}: RegBits = RegBits(start={lsb}, end={msb})"""
            ), ' ' * 8))

    def _emit_registers(self, f: TextIO, xml_peripheral, peripheral_base_addr: int) -> None:
        for register in xml_peripheral.xpath('./registers/register'):
            name: str = self._get_node_text(register, 'name')
            access: str = self._get_node_text(register, 'access')
            addr_offset: int = du.cast_str(self._get_node_text(register, 'addressOffset'))
            descr: str = self._get_node_text(register, 'description')
            reset_value: str = self._get_node_text(register, 'resetValue')

            self._device_regs.append((name, peripheral_base_addr + addr_offset))

            decr_formatted: str = tw.indent(tw.fill(descr, width=80), ' '*4)
            description = tw.indent(f"{os.linesep}Description:{os.linesep}{decr_formatted}", ' ' * 4) \
                if descr else ''

            f.write(tw.dedent(f'''

                class {self._reg_prefix}{name}(RegBaseDott):
                    """
                    Access: [{access}]
                    Reset value: {reset_value} %s
                    """
                    def __init__(self, reg_addr: int, dr: DeviceRegsDott) -> None:
                        super().__init__(reg_addr, dr)''') %
                    description)

            self._emit_regbits(f, register)

            f.write(os.linesep)

    def _emit_peripherals(self, f: TextIO) -> None:
        for peripheral in self._svd_xml.xpath('/device/peripherals/peripheral'):
            name: str = self._get_node_text(peripheral, 'name')
            peripheral_base_addr: int = du.cast_str(self._get_node_text(peripheral, 'baseAddress'))
            f.write(tw.dedent(f"""

                ###############################################################################
                # Peripheral:   {name}
                # Base Address: {hex(peripheral_base_addr)}"""
            ))

            self._emit_registers(f, peripheral, peripheral_base_addr)

    def generate(self) -> None:
        """
        Reads the XML file set in the constructor and writes the DOTT register file to the file
        specified in the constructor.
        """
        if not self._device_name:
            self._device_name = self._get_node_text(self._svd_xml, "/device/name")

        license_raw: str = self._svd_xml.find('licenseText').text
        license_raw = os.linesep.join([line.strip() for line in license_raw.splitlines()])
        license_raw = os.linesep.join([line.replace('\\n\\n', os.linesep) for line in license_raw.splitlines()])
        license_raw = os.linesep.join([line.replace('\\n\\n', '') for line in license_raw.splitlines()])

        with open(self._out_file, 'w', encoding='ascii', newline=self._newline) as f:
            license_formatted: str = (f'"""\r{inspect.cleandoc(license_raw) if license_raw else ""}\r"""{os.linesep}')
            f.write(inspect.cleandoc(f'''%s
                # This file is automatically generated from an SVD register description using {basename(__file__)}.
                # This file is NOT meant to be modified manually!

                import typing

                from dottmi.reg_access import RegBaseDott, DeviceRegsDott, RegBits

                if typing.TYPE_CHECKING:
                    from dottmi.dott import Target

                # Intentionally disable selected pylint warnings.
                # pylint: disable=line-too-long
                # pylint: disable=invalid-name
                # pylint: disable=too-many-instance-attributes
                # pylint: disable=too-few-public-methods
                # pylint: disable=too-many-statements
                # pylint: disable=too-many-lines
            ''') % license_formatted)
            f.write(os.linesep)

            self._emit_peripherals(f)
            self._emit_device_registers(f)


def main():
    """
    Main.
    # TODO: add support for multiple input files.
    """
    parser = argparse.ArgumentParser(prog='svd2dott',
                                     description='Converts CMSIS SVD files to DOTT-compatible register access classes')

    parser.add_argument('-i', '--input', dest='input', required=True,
                        help='SVD input file')
    parser.add_argument('-o', '--output', dest='output', required=True,
                        help='DOTT register Python file')
    parser.add_argument('-d', '--device', dest='device', required=False, default=None,
                        help='Device name. Overrides device name in SVD file.')
    parser.add_argument('-r', '--reg-prefix', dest='reg_prefix', required=False, default=None,
                        help='Register class prefix (default is none).')
    parser.add_argument('-n', '--newline', dest='newline', required=False, type=str,
                        choices=['unix', 'dos'], default='unix',
                        help='Newline type (unix, dos) used in output file.')

    args = parser.parse_args()

    # set newline depending on user input
    newline: str = '\n'
    if args.newline == 'dos':
        newline = '\r\n'

    svd2dott = SVD2Dott(args.input,
                        args.output,
                        args.device,
                        newline,
                        args.reg_prefix)
    svd2dott.generate()


if __name__ == '__main__':
    main()
