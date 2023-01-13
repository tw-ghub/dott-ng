import pytest

from dottmi.target_mem import TypedPtr, TargetMemModel
from dottmi.utils import DottConvert, log
from dottmi.dott import DottConf, dott
from dottmi.breakpoint import HaltPoint, InterceptPoint, InterceptPointCmds
from dottmi.fixtures import target_load_symbols_only


class TestBasic(object):
    @pytest.mark.dott_mem(model=TargetMemModel.NOALLOC)
    def test_cpuid(self, target_load_symbols_only, target_reset):
        dt = dott().target
        dc = DottConvert
        log.debug('0x%x' % dt.eval('$pc'))
        cpuid = dc.bytes_to_uint32(dt.mem.read(0xE000ED00, 4))
        log.debug('CPUID 0x%x' % cpuid)
        assert cpuid == 0x410cc200  # Cortex-M0
