# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022-2024 Thomas Winkler <thomas.winkler@gmail.com>
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

from __future__ import annotations  # available from Python 3.7 onwards, default from Python 3.11 onwards

import pytest
import types
import typing

if typing.TYPE_CHECKING:
    from dottmi.target import Target

from typing import Dict
from dottmi.breakpoint import HaltPoint, InterceptPoint
from dottmi.dott import DottConf, dott
from dottmi.dottexceptions import DottException
from dottmi.pylinkdott import TargetDirect
from dottmi.target_mem import TargetMemModel, TargetMemTestHook, TargetMem, TargetMemNoAlloc
from dottmi.utils import log


# ----------------------------------------------------------------------------------------------------------------------
def target_load_common(name: str, load_to_flash: bool, silent: bool = False, dt: Target = None) -> None:
    dt = dott().target if dt is None else dt
    if dt is None:
        log.error('Connection to target (via JLINK) was not properly established. Please check your JLINK parameters!')
        pytest.exit('Aborting test execution.')

    try:
        if not silent:
            log.info(f'Triggering download of APP to {name}...')

        # optionally load bootloader binary (load elf ONLY - symbols are loaded after the app)
        bl_load_elf = dt.dconf.get(DottConf.keys.bl_load_elf)
        if bl_load_elf is not None:
            dt.load(bl_load_elf, None, enable_flash=load_to_flash)

        # load application binaries
        app_load_elf = dt.dconf.get(DottConf.keys.app_load_elf)
        app_symbol_elf = dt.dconf.get(DottConf.keys.app_symbol_elf)
        if app_load_elf is not None:
            dt.load(app_load_elf, app_symbol_elf, enable_flash=load_to_flash)

        # add bootloader symbol file; note: it is important to this 'add' so after doing target.load() with symbol elf.
        bl_symbol_elf = dt.dconf.get(DottConf.keys.bl_symbol_elf)
        if bl_symbol_elf is not None:
            dt.cli_exec('add-symbol-file %s 0x%x' % (bl_symbol_elf, int(dt.dconf.get(DottConf.keys.bl_symbol_addr))))

        # disable FLASH breakpoints
        dt.monitor.enable_flash_breakpoints(False)
    except Exception as ex:
        log.exception(str(ex))
        pytest.exit('Unhandled exception target download. See trace above.')


# ----------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope='function')
def target_load_sram() -> None:
    """
    This fixture loads the application (and optionally the bootloader) binary onto the target SRAM.
    This fixture has FUNCTION scope and hence is executed for each test where it is specified.
    """
    target_load_common('SRAM', load_to_flash=False)


# ----------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope='session')
def target_load_flash(silent: bool = False) -> None:
    """
    This fixture loads the application (and optionally the bootloader) binary onto the target FLASH. This fixture has
    SESSION scope and hence is executed once per test session and not for every test where it is specified.
    """
    target_load_common('FLASH', load_to_flash=True, silent=silent)


# ----------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope='function')
def target_load_flash_always(silent: bool = False) -> None:
    """
    This fixture loads the application (and optionally the bootloader) binary onto the target FLASH. This fixture has
    FUNCTION scope and hence is executed for each test where it is specified.

    Args:
        silent: If not used as fixture but called directly the silent argument allows to control if the function prints
                informative output or not.
    """
    target_load_common('FLASH', load_to_flash=True, silent=silent)


# ----------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope='function')
def target_load_symbols_only(silent: bool = False) -> None:
    """
    This fixture loads the symbols from the app_symbol_elf file but does NOT perform actual target download. Hence,
    this fixture is useful if the code has already been loaded onto the target before and only symbol information
    is needed in the test.
    """
    app_symbol_elf = DottConf.get('app_symbol_elf')
    dott().target.load(None, app_symbol_elf, enable_flash=False)


# ----------------------------------------------------------------------------------------------------------------------
def _target_mem_init_noalloc(dt: Target = None) -> None:
    dt = dott().target if dt is None else dt

    # print mem model override information
    if dt.dconf.get(DottConf.keys.on_target_mem_model) != TargetMemModel.NOALLOC:
        log.info(f'Overriding std. target mem model with {TargetMemModel.NOALLOC}.')

    # define the initial test breakpoint, start the target and wait until the breakpoint is reached
    bp = HaltPoint('main', target=dt)
    dt.cont()
    try:
        bp.wait_complete(timeout=float(dt.dconf.get(DottConf.keys.fixture_timeout)))
    except Exception:
        dt.halt()
        log.warning('main not reached. Target halted after timeout at PC: 0x%x' % dt.eval('$pc'))

    # remove test hook breakpoint
    bp.delete()

    # once we have reached the initial breakpoint we initialize the on-target memory access model
    dt.mem = TargetMemNoAlloc(dt)

    yield


# ----------------------------------------------------------------------------------------------------------------------
def _target_mem_init_testhook(dt: Target = None) -> None:
    dt = dott().target if dt is None else dt

    # print mem model override information
    if dt.dconf.get(DottConf.keys.on_target_mem_model) != TargetMemModel.TESTHOOK:
        log.info(f'Overriding std. target mem model with {TargetMemModel.TESTHOOK}.')

    # define the initial test breakpoint, start the target and wait until the breakpoint is reached
    bp = HaltPoint('DOTT_test_hook_chained', target=dt)
    dt.cont()
    try:
        bp.wait_complete(timeout=float(dt.dconf.get(DottConf.keys.fixture_timeout)))
    except Exception:
        dt.halt()
        log.warning('DOTT_test_hook_chained not reached. Target halted after timeout at PC: 0x%x' % dt.eval('$pc'))

    # remove test hook breakpoint
    bp.delete()

    # once we have reached the initial breakpoint we initialize the on-target memory access model
    dt.mem = TargetMemTestHook(dt)

    yield


# ----------------------------------------------------------------------------------------------------------------------
def _target_mem_init_prestack(mem_model_args: Dict = None, dt: Target = None) -> None:
    dt = dott().target if dt is None else dt
    override = False

    # override default value of on-target memory size
    target_mem_num_bytes: int = dt.dconf.get(DottConf.keys.on_target_mem_prestack_alloc_size)
    if mem_model_args is not None and 'alloc_size' in mem_model_args:
        target_mem_num_bytes = int(mem_model_args['alloc_size'])
        override = True
    if target_mem_num_bytes % 4 != 0:
        raise DottException('The num_bytes argument for prestack memory allocation shall be a multiple of 4!')

    # override default value for target alloc location
    alloc_location: str = dt.dconf.get(DottConf.keys.on_target_mem_prestack_alloc_location)
    if mem_model_args is not None and 'alloc_location' in mem_model_args:
        alloc_location = str(mem_model_args['alloc_location'])
        override = True

    # override default value for target halt location
    halt_location: str = dt.dconf.get(DottConf.keys.on_target_mem_prestack_halt_location)
    if mem_model_args is not None and 'halt_location' in mem_model_args:
        halt_location = str(mem_model_args['halt_location'])
        override = True

    # override default value for target total_stack_size
    total_stack_num_bytes: int = dt.dconf.get(DottConf.keys.on_target_mem_prestack_total_stack_size)
    if mem_model_args is not None and 'total_stack_size' in mem_model_args:
        total_stack_num_bytes = mem_model_args['total_stack_size']
        override = True

    # print mem model override information
    if override:
        log.info(f'Overriding std. target mem model with {TargetMemModel.PRESTACK}'
                 f'({target_mem_num_bytes}bytes '
                 f'@{alloc_location}; '
                 f'halt @{halt_location}; '
                 f'total stack: {total_stack_num_bytes if total_stack_num_bytes is not None else "unknown"}).')

    # define the initial allocation breakpoint, start the target and wait until the breakpoint is reached
    bp = HaltPoint(alloc_location, target=dt)
    dt.cont()
    try:
        bp.wait_complete(timeout=float(dt.dconf.get(DottConf.keys.fixture_timeout)))
    except Exception:
        dt.halt()
        log.warning(f'{alloc_location} not reached. Target halted after timeout at PC: 0x{dt.eval("$pc"):x}')
    bp.delete()

    # adjust the stack pointer (i.e., steal the requested amount of on-target memory)
    dt.eval(f'$sp -= {target_mem_num_bytes}')

    # initialize the on-target memory access model using the 'stolen' memory
    target_mem_stack_start = dt.eval('$sp')
    dt.mem = TargetMem(dt, target_mem_stack_start, target_mem_num_bytes)

    # define the halt breakpoint, start the target and wait until the breakpoint is reached
    bp = HaltPoint(halt_location, target=dt)
    dt.cont()
    try:
        bp.wait_complete(timeout=float(dt.dconf.get(DottConf.keys.fixture_timeout)))
    except Exception:
        dt.halt()
        log.warning(f'{halt_location} not reached. Target halted after timeout at PC: 0x{dt.eval("$pc"):x}')
    bp.delete()

    # pass control to test
    yield


# ----------------------------------------------------------------------------------------------------------------------
def target_reset_common(request, sp: str = None, pc: str = None, setup_cb: types.FunctionType = None, dt: Target = None) -> None:
    dt = dott().target if dt is None else dt
    # reset target and clear all potentially existing breakpoints
    dt.halt()
    dt.reset()
    dt.bp_clear_all()

    # set sp and pc for execution from RAM area
    if sp is not None:
        dt.eval(f'$sp = *{sp}')
    if pc is not None:
        dt.eval(f'$pc = *{pc}')

    # if a callback was specified give user code a chance to do early device initialization
    if setup_cb is not None:
        setup_cb()

    # set on-target memory allocation model either from config or from pytest marker
    mem_model: TargetMemModel = dt.dconf.get(DottConf.keys.on_target_mem_model)
    mem_model_args = None
    if 'pytestmark' in request.keywords:
        for m in request.keywords['pytestmark']:
            if m.name == 'dott_mem' and 'model' in m.kwargs:
                mem_model = m.kwargs['model']
                mem_model_args = m.kwargs
                break

    if mem_model == TargetMemModel.NOALLOC:
        yield from _target_mem_init_noalloc(dt=dt)
    elif mem_model == TargetMemModel.TESTHOOK:
        yield from _target_mem_init_testhook(dt=dt)
    elif mem_model == TargetMemModel.PRESTACK:
        yield from _target_mem_init_prestack(mem_model_args, dt=dt)
    else:
        log.warning(f'Selected target memory allocation model is not implemented!')


# ----------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope='function')
def target_reset_sram(request) -> None:
    """
    This fixture halts the target devices, resets it and clears all potentially active breakpoints. Additionally, it
    sets the SP and PC to the default Cortex-M on-chip SRAM locations (0x20000000 and 0x20000004). The target memory
    model can be selected either via the global config system or via the pytest marker 'dott_mem' where the model
    argument is one of the models specified in TargetMemModel.

    Args:
        request: PyTest request object.
    """
    yield from target_reset_common(request, sp='0x20000000', pc='0x20000004')


# ----------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope='function')
def target_reset_flash(request) -> None:
    """
    This fixture halts the target device, resets it and clears all potentially active breakpoints. The target memory
    model can be selected either via the global config system or via the pytest marker 'dott_mem' where the model
    argument is one of the models specified in TargetMemModel.
    Args:
        request: PyTest request object.
    """
    yield from target_reset_common(request)


# ----------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope='function')
def live_access():
    """
    This fixture provides access to target memory while the target is running.

    Returns: Instance of TargetLive which provides memory read/write functions while target is running.
    """
    live = TargetDirect()
    yield live
    live.disconnect()


# ----------------------------------------------------------------------------------------------------------------------
# DOTT-internal fixture which performs DOTT related cleanup on a per-function basis
@pytest.fixture(scope='function', autouse=True)
def dott_auto_func_cleanup():
    yield
    dott().target.halt()
    InterceptPoint.delete_all()


def pytest_configure(config):
    # register markers with pytest
    config.addinivalue_line("markers", "dott_mem: marker to select on-target memory allocation model")


def pytest_collection_finish() -> None:
    """
    If you are using the default target in your set setup you may want to import this function in your pytest
    conftest.py file. This initializes the default target and ensures that the DottConf output is printed before the
    first test is run.
    """
    dott()
