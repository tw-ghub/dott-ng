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
    def __init__(self, svd_file: str, additional_svd_files: List[str], out_file: str, device_name: str | None = None,
                 newline: str = '\n', reg_prefix: str | None = None, use_peripheral_prefix: bool = False,
                 reg_group: bool = False) -> None:
        self._additional_svd_files: List[str] = additional_svd_files
        self._device_name: str | None = device_name
        self._device_regs: List[Tuple[str, str, int]] = []  # reg name, peripheral name, reg address
        self._license_text: str | None = None
        self._newline = newline
        self._out_file: str = out_file
        self._reg_prefix: str = reg_prefix if reg_prefix else ''
        self._reg_group: bool = reg_group
        self._use_peripheral_prefix: bool = use_peripheral_prefix
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

        for reg, periph, addr in self._device_regs:
            preg = f'{self._reg_prefix}{reg}'
            f.write(tw.indent(f'self.{preg} = {preg}({hex(addr)}, self){self._newline}', ' '*8))

    def _emit_device_peripherals_and_registers(self, f: TextIO) -> None:
        active_periph: str | None = None
        for reg, periph, addr in self._device_regs:
            if periph != active_periph:
                active_periph = periph
                f.write(tw.dedent(f'''
                    class Peripheral{periph}:
                        """
                        This class instantiates all registers of peripheral {periph} together with their address.
                        """
                        def __init__(self, dev: DeviceRegsDott) -> None:
                '''))

            preg = f'{self._reg_prefix}{reg}'
            reg_stripped: str = reg.removeprefix(f'{periph}_')
            f.write(tw.indent(f'self.{reg_stripped} = {preg}({hex(addr)}, dev){self._newline}', ' '*8))

        f.write(tw.dedent(f'''
            class {self._device_name}Registers(DeviceRegsDott):
                """
                This class instantiates all device peripherals of device {self._device_name}.
                """
                def __init__(self, dt: Target | None = None) -> None:
                    super().__init__(dt)
        '''))

        active_periph: str | None = None
        for reg, periph, addr in self._device_regs:
            if periph != active_periph:
                f.write(tw.indent(f'self.{periph} = Peripheral{periph}(self){self._newline}', ' ' * 8))
                active_periph = periph

    def _do_overlap(self, lsb: int, msb: int, lsb_last: int, msb_last: int) -> bool:
        last_set = set(range(lsb_last, msb_last +1 ))
        current = range(lsb, msb + 1)
        interect_len: int  = len(last_set.intersection(current))
        return False if interect_len == 0 else True

    def _emit_regbits(self, f: TextIO, xml_register, register_name: str) -> None:
        lsb_last: int | None = None
        msb_last: int | None = None

        name_last: str = ''
        for regbits in xml_register.xpath("./fields/field"):
            name: str = self._get_node_text(regbits, "name")

            if len(regbits.xpath('lsb')) > 0:
                lsb: str = self._get_node_text(regbits, 'lsb')
                msb: str = self._get_node_text(regbits, 'msb')
            elif len(regbits.xpath('bitOffset')) > 0:
                lsb: str = self._get_node_text(regbits, 'bitOffset')
                bit_width: str = self._get_node_text(regbits, 'bitWidth')
                msb: str = f'{du.cast_str(lsb) + du.cast_str(bit_width) - 1}'
            else:
                raise ValueError('Only bitRangeLsbMsbStyle and bitRangeOffsetWidthStyle are supported.')

            f.write(tw.indent(tw.dedent(f"""
                self.{name}: int = 0x0
                self._bits_{name}: RegBits = RegBits(start={lsb}, end={msb})"""
            ), ' ' * 8))

            lsb_i = du.cast_str(lsb)
            msb_i = du.cast_str(msb)
            if lsb_last is not None and msb_last is not None:
                if self._do_overlap(lsb_i, msb_i, lsb_last, msb_last):
                    print(f'WARNING: Overlap detected for {register_name}.{name} and {register_name}.{name_last}. '
                          f'Please check (and correct) input data!')
            lsb_last = lsb_i
            msb_last = msb_i
            name_last = name

    def _emit_registers(self, f: TextIO, xml_peripheral, peripheral_base_addr: int) -> None:
        peripheral_name: str = self._get_node_text(xml_peripheral, 'name')
        for register in xml_peripheral.xpath('./registers/register'):
            name: str = self._get_node_text(register, 'name')
            if self._use_peripheral_prefix:
                name = f'{peripheral_name}_{name}'
            try:
                access: str = self._get_node_text(register, 'access')
            except ValueError:
                access = ''
            addr_offset: int = du.cast_str(self._get_node_text(register, 'addressOffset'))

            try:
                descr: str = self._get_node_text(register, 'description')
            except:
                descr: str = ''
            try:
                reset_value: str = self._get_node_text(register, 'resetValue')
            except:
                reset_value: str = ''

            self._device_regs.append((name, peripheral_name, peripheral_base_addr + addr_offset))

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

            self._emit_regbits(f, register, name)

            f.write(os.linesep)

    def _emit_peripherals(self, f: TextIO) -> None:
        for peripheral in self._svd_xml.xpath('/device/peripherals/peripheral'):
            name: str = self._get_node_text(peripheral, 'name')
            try:
                peripheral_base_addr: int = du.cast_str(self._get_node_text(peripheral, 'baseAddress'))
            except:
                continue
            f.write(tw.dedent(f"""

                ###############################################################################
                # Peripheral:   {name}
                # Base Address: {hex(peripheral_base_addr)}"""
            ))

            self._emit_registers(f, peripheral, peripheral_base_addr)

    def _merge_peripherals(self) -> None:
        primary_peripherals = self._svd_xml.xpath('/device/peripherals')[0]

        for add_file in self._additional_svd_files:
            print(f'Merging {add_file}')
            add_xml = lxml.etree.parse(add_file)
            add_peripherals = add_xml.xpath('/device/peripherals/*')

            if add_peripherals:
                for peripheral in add_peripherals:
                    primary_peripherals.append(peripheral)

    def generate(self) -> None:
        """
        Reads the XML file set in the constructor and writes the DOTT register file to the file
        specified in the constructor.
        """
        self._merge_peripherals()

        if not self._device_name:
            self._device_name = self._get_node_text(self._svd_xml, "/device/name")

        try:
            license_raw: str = self._svd_xml.find('licenseText').text
            license_raw = os.linesep.join([line.strip() for line in license_raw.splitlines()])
            license_raw = os.linesep.join([line.replace('\\n\\n', os.linesep) for line in license_raw.splitlines()])
            license_raw = os.linesep.join([line.replace('\\n\\n', '') for line in license_raw.splitlines()])
        except:
            license_raw: str = ''

        with open(self._out_file, 'w', encoding='ascii', newline=self._newline) as f:
            license_formatted: str = f'"""\r{inspect.cleandoc(license_raw) if license_raw else ""}\r"""{os.linesep}'
            f.write(inspect.cleandoc(f'''%s
                # This file is automatically generated from an SVD register description using {basename(__file__)}.
                # This file is NOT meant to be modified manually!

                import typing

                from dottmi.reg_access import RegBaseDott, DeviceRegsDott, RegBits
                from dottmi.target import Target

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
            if self._reg_group:
                self._emit_device_peripherals_and_registers(f)
            else:
                self._emit_device_registers(f)


def main():
    """
    Main. Performs argument parsing and triggers the SDV conversion.
    """
    parser = argparse.ArgumentParser(prog='svd2dott',
                                     description='Converts CMSIS SVD files to DOTT-compatible register access classes')

    parser.add_argument('-i', '--input', dest='input', nargs='+', required=True,
                        help='SVD input files. The first one is the primary one. Additional, optional input SVD '
                             'files can be given. Their "peripherals" sections are merged into the primary SVD file.')
    parser.add_argument('-o', '--output', dest='output', required=True,
                        help='DOTT register Python file')
    parser.add_argument('-d', '--device', dest='device', required=False, default=None,
                        help='Device name. Overrides device name in SVD file.')
    parser.add_argument('-r', '--reg-prefix', dest='reg_prefix', required=False, default=None,
                        help='Register class prefix (default is none).')
    parser.add_argument('-p', '--reg-peripheral-prefix', dest='reg_peripheral_prefix', required=False,
                        default=False, action='store_true',
                        help='Use peripheral name as prefix for register class (default is none). Mutual exclusive with -r.')
    parser.add_argument('-g', '--group-regs', dest='reg_group', required=False, default=False,
                        action='store_true', help='Group registers based on the peripheral they belong to (implies also -p).')
    parser.add_argument('-n', '--newline', dest='newline', required=False, type=str,
                        choices=['unix', 'dos'], default='unix',
                        help='Newline type (unix, dos) used in output file.')

    args = parser.parse_args()

    primary_input: str = args.input[0]
    additional_input: List[str] = args.input[1:]

    # set newline depending on user input
    newline: str = '\n'
    if args.newline == 'dos':
        newline = '\r\n'

    if args.reg_group:
        args.reg_peripheral_prefix = True

    svd2dott = SVD2Dott(primary_input,
                        additional_input,
                        args.output,
                        args.device,
                        newline,
                        args.reg_prefix,
                        args.reg_peripheral_prefix,
                        args.reg_group)
    svd2dott.generate()


if __name__ == '__main__':
    main()
