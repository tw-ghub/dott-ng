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
import glob
import os
import subprocess
import time

import pytest

from dottmi.dott import dott
from dottmi.utils import log


def setup_module(request):
    """
    Generate all register access classes required by the tests.
    """
    TestSvd.create_reg_file('regs_stm32f072x.py')
    TestSvd.create_reg_file('regs_prefix_stm32f072x.py', args='-r Reg_')
    TestSvd.create_reg_file('regs_device_stm32f072x.py', args='-d Nucleo')
    TestSvd.create_reg_file('regs_merged_stm32f072x.py',
                            in_file='03_snippets/host/data/STM32F072x.svd 03_snippets/host/data/Cortex-M0.svd')
    TestSvd.create_reg_file('regs_cortexm0.py', in_file=f'03_snippets/host/data/Cortex-M0.svd')


def teardown_module(request):
    """
    Cleanup of generated register access classes.
    Args:
        request:

    Returns:

    """
    for f in glob.glob('03_snippets/host/regs_*.py'):
        os.remove(f)


class TestSvd:
    @staticmethod
    def create_reg_file(out_file: str, in_file: str | None = None, args: str = '') -> None:
        out_name: str = f'03_snippets/host/{out_file}'
        in_name: str = in_file if in_file else '03_snippets/host/data/STM32F072x.svd'
        if os.path.exists(out_name):
            os.remove(out_name)

        if os.environ.get('JENKINS_HOME'):
            log.debug('Running on Jenkins.')
            pptmp = os.environ.get('PYTHONPATH')
            os.environ['PYTHONPATH'] = ''
            os.system(f'svd2dott -i {in_name} -o {out_name} {args}')
            os.environ['PYTHONPATH'] = pptmp
        else:
            log.debug('NOT running on Jenkins.')
            os.system(f'python ../dottmi/svd2dott.py -i {in_name} -o {out_name} {args}')

    def test_stm32f072(self, target_load, target_reset):
        """
        Access registers on STM32 and checks if they are having the expected reset value.
        """
        from .regs_stm32f072x import STM32F072xRegisters

        stm32_regs = STM32F072xRegisters()

        stm32_regs.CFGR.fetch()
        log.debug('0x%x' % stm32_regs.CFGR.raw)
        assert stm32_regs.CFGR.raw == 0x2022bb7f
        stm32_regs.PRER.fetch()
        log.debug('0x%x' % stm32_regs.PRER.raw)
        assert stm32_regs.PRER.raw == 0x007F00FF

    def test_stm32f072_prefix(self, target_load, target_reset):
        """
        Same test as previous one but using prefix for registers (supplied via command line parameter).
        """
        from .regs_prefix_stm32f072x import STM32F072xRegisters

        stm32_regs = STM32F072xRegisters()

        stm32_regs.Reg_CFGR.fetch()
        log.debug('0x%x' % stm32_regs.Reg_CFGR.raw)
        assert stm32_regs.Reg_CFGR.raw == 0x2022bb7f
        stm32_regs.Reg_PRER.fetch()
        log.debug('0x%x' % stm32_regs.Reg_PRER.raw)
        assert stm32_regs.Reg_PRER.raw == 0x007F00FF

    def test_stm32f072_device(self, target_load, target_reset):
        """
        same test as previous one but using device name (supplied via command line paramter).
        """
        from .regs_device_stm32f072x import NucleoRegisters

        stm32_regs = NucleoRegisters()

        stm32_regs.CFGR.fetch()
        log.debug('0x%x' % stm32_regs.CFGR.raw)
        assert stm32_regs.CFGR.raw == 0x2022bb7f
        stm32_regs.PRER.fetch()
        log.debug('0x%x' % stm32_regs.PRER.raw)
        assert stm32_regs.PRER.raw == 0x007F00FF

    def test_svd2dott_merge(self, target_load, target_reset):
        """
        Creates register access class from two SVD files which are merged.
        """
        from .regs_merged_stm32f072x import STM32F072xRegisters

        stm32_regs = STM32F072xRegisters()
        stm32_regs.AIRCR.fetch()
        log.debug('0x%x' % stm32_regs.AIRCR.raw)

        stm32_regs.CFGR.fetch()
        log.debug('0x%x' % stm32_regs.CFGR.raw)
        assert stm32_regs.CFGR.raw == 0x2022bb7f
        stm32_regs.PRER.fetch()
        log.debug('0x%x' % stm32_regs.PRER.raw)
        assert stm32_regs.PRER.raw == 0x007F00FF

    def test_cpuid(self, target_load, target_reset):
        """
        Creates register access class from two SVD files which are merged. Reads out and checks the CPUID register.
        """
        from .regs_merged_stm32f072x import STM32F072xRegisters

        dt = dott().target
        stm32_regs = STM32F072xRegisters(dt)

        stm32_regs.CPUID.fetch()
        assert stm32_regs.CPUID.raw == 0x410cc200
        assert stm32_regs.CPUID.Implementer == 0x41  # ARM
        assert stm32_regs.CPUID.Constant == 0xc  # ARMv6-M
        assert stm32_regs.CPUID.Partno == 0xc20  # Cortex-M0
        assert stm32_regs.CPUID.Revision == 0x0  # r0p0

        log.debug(f'\nCPUID\n{stm32_regs.CPUID}')

    def test_cpuid_monitor(self, target_load, target_reset):
        """
        Creates register access class from two SVD files which are merged. Reads out and checks the CPUID register
        via monitor access.
        """
        from .regs_merged_stm32f072x import STM32F072xRegisters

        dt = dott().target
        stm32_regs = STM32F072xRegisters(dt)

        with stm32_regs.CPUID as cpuid:
            # note: fetch is done automatically when entering the monitor
            assert cpuid.raw == 0x410cc200
            assert cpuid.Implementer == 0x41  # ARM
            assert cpuid.Constant == 0xc  # ARMv6-M
            assert cpuid.Partno == 0xc20  # Cortex-M0
            assert cpuid.Revision == 0x0  # r0p0

            log.debug(f'\nCPUID\n{cpuid}')

    def test_reset(self, target_load, target_reset):
        """
        Creates register access class from two SVD files which are merged.
        Resets the system via the SCB AIRC register (field SYSRESETREQ).
        """
        from .regs_merged_stm32f072x import STM32F072xRegisters

        dt = dott().target
        stm32_regs = STM32F072xRegisters(dt)

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
        with stm32_regs.AIRCR as r:
            # note: fetch done automatically
            r.VECTKEY = 0x05FA
            r.SYSRESETREQ = 0x1
            log.debug('0x%x' % r.raw)
        # note: commit done automatically

        # let target run and initialize
        dt.cont()
        time.sleep(1)
        dt.halt()

        # global_data is expected to have been initialized again to deadbeef and incremented from there
        gd = dt.eval('global_data')
        assert gd > 0xdeadbeef
