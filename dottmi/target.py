# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022-2025 Thomas Winkler <thomas.winkler@gmail.com>
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

import logging
import os
import threading
import time
import traceback
from pathlib import Path, PurePosixPath
from typing import Dict, Union, List, TYPE_CHECKING

import dottmi.utils
from dottmi.dott import DottHooks
from dottmi.dott_conf import DottConf, DottConfExt
from dottmi.utils import requires_rt_ge_2

if TYPE_CHECKING:
    from dottmi.target_mem import TargetMem

from dottmi.breakpointhandler import BreakpointHandler
from dottmi.dottexceptions import DottException
from dottmi.gdb import GdbClient, GdbServer
from dottmi.gdb_mi import NotifySubscriber
from dottmi.monitor import Monitor
from dottmi.symbols import BinarySymbols
from dottmi.target_mem import TargetMem, TargetMemNoAlloc
from dottmi.utils import cast_str, log

logging.basicConfig(level=logging.DEBUG)


class Target(NotifySubscriber):

    def __init__(self, gdb_server: GdbServer, gdb_client: GdbClient, monitor: Monitor, dconf: [DottConf | DottConfExt], auto_connect: bool = True) -> None:
        """
        Creates a target which represents a target device. It requires both a GDB server (either started by DOTT
        or started externally) and a GDB client instance used to connect to the GDB server.
        If auto_connect is True (the default) the connected from GDB client to GDB server is automatically established.
        """
        NotifySubscriber.__init__(self, name='Target', process_in_thread=True)
        self._dconf: [DottConf | DottConfExt] = dconf
        self._load_elf_file_name = None
        self._symbol_elf_file_name = None

        self._device_name: str = dconf.get(DottConf.keys.device_name)
        self._device_endianess: str = dconf.get(DottConf.keys.device_endianess)
        self._gdb_client: GdbClient = gdb_client
        self._gdb_server: GdbServer = gdb_server
        self._monitor: Monitor = monitor
        self._monitor.set_target(self)

        # condition variable and status flag used to implement helpers
        # allowing callers to wait until target is stopped or running
        self._cv_target_state: threading.Condition = threading.Condition()
        self._is_target_running: bool = True
        self._target_state_change_reason: str | None = None
        # counters to keep track how many (threads) are lined to for a stage change notifications
        self._wait_running_cnt: int = 0
        self._wait_halted_cnt: int = 0

        # Default number of seconds to wait for a target state change (i.e., halt -> running and vice versa) before
        # raising a timeout exception.
        self._state_change_wait_secs: float = 5.0

        # instantiate delegates
        self._symbols: BinarySymbols = BinarySymbols(self)
        self._mem: TargetMem = TargetMemNoAlloc(self)

        # start breakpoint handler
        self._bp_handler: BreakpointHandler = BreakpointHandler()
        self._gdb_client.gdb_mi.response_handler.notify_subscribe(self._bp_handler, 'stopped', 'breakpoint-hit', high_prio=False)

        # register to get notified if the target state changes
        self._gdb_client.gdb_mi.response_handler.notify_subscribe(self, 'stopped', None, high_prio=True)
        self._gdb_client.gdb_mi.response_handler.notify_subscribe(self, 'running', None, high_prio=True)

        # delay after device startup / continue
        self._startup_delay: float = 0.0

        # timeout used when connection to remote GDB server ("target remote")
        self._connect_timeout: float = float(dconf.get(DottConf.keys.gdb_server_connect_timeout))

        # flag which indicates if gdb client is attached to target
        self._gdb_client_is_connected = False

        if auto_connect:
            self.gdb_client_connect()

    def gdb_client_connect(self) -> None:
        """
        Connects the GDB client instance to the GDB server.
        """
        if self._gdb_server is None:
            raise DottException('No GDB server instance set. If you disconnected the GDB client and now try to connect '
                                'it again you may need to create and set a new GDB server instance (because DOTT '
                                'auto-launches JLINK GDB server in singlerun mode.')

        try:
            # Hook called before connection to GDB server is established.
            DottHooks.exec_gdb_pre_connect_hook(self)

            self.exec('-gdb-set mi-async on', timeout=5)
            self.exec(f'-target-select remote {self._gdb_server.addr}:{self._gdb_server.port}', self._connect_timeout)
            self.cli_exec('set mem inaccessible-by-default off', timeout=1)
        except Exception as ex:
            raise ex

        # source script with custom GDB commands (custom Python commands executed in GDB context)
        my_dir = Path(__file__).absolute().parent
        gdb_script_file = my_dir.joinpath('./gdb_cmds.py')

        # note: GDB expects paths to be POSIX-formatted.
        gdb_script_file = str(PurePosixPath(gdb_script_file))
        self.cli_exec(f'source {gdb_script_file}')

        self._gdb_client_is_connected = True

    def gdb_client_disconnect(self, ignore_timeout=False) -> None:
        """
        Disconnects the GDB client from the GDB server. The target is not resumed.
        Since DOTT auto-launches JLINK GDB server in 'singlerun' mode, the GDB server process terminates when
        the GDB client disconnects. The internal state is updated accordingly by calling gdb_server_stop().
        This means that the user is required to create and set a new GDB server instance before connecting
        the target's gdb client again.
        Important: For reasons of consistency, this is also done that way if the GDB server was not started by
                   DOTT. Also in this case, a new GDB server object needs to be creates and set.

        Args: ignore_timeout: Ignore a potential timeout when sending the disconnect command to GDB client.
                              This may be useful when the target has been reset and GDB is not aware of it.
        """
        if self._gdb_client_is_connected:
            try:
                self.cli_exec('disconnect', timeout=1)
            except Exception as ex:
                if not ignore_timeout:
                    raise ex
        self._gdb_client_is_connected = False
        self.gdb_server_stop()

    def gdb_server_stop(self) -> None:
        """
        Stops the GDB server. The GDB client must have been disconnected before.
        """
        if self._gdb_client_is_connected:
            raise DottException("Can not terminate GDB server while client is connected. Disconnect client first!")
        if self._gdb_server is not None:
            self._gdb_server.shutdown()
            self._gdb_server = None

    def gdb_server_set(self, gdb_server: GdbServer) -> None:
        """
        Allows to set a gdb server instance for the target. Can only be called if there is no gdb server instance
        set so far or the current gdb server instance has been stopped.
        """
        if self._gdb_server is not None:
            raise DottException('Can not set GDB server is there currently is an instance in place. Stop the current'
                                'GDB server before setting a new one!')

        self._gdb_server = gdb_server

    def disconnect(self) -> None:
        """
        Disconnect first closes the GDB client connection and then terminates the GDB server. The target is not resumed.
        After calling disconnect, the target instance can no longer be used (i.e., there is not reconnect).
        """
        if self._gdb_client is not None:
            self.exec_noblock('-gdb-exit')
            self._gdb_client = None
            self._gdb_client_is_connected = False
        if self._gdb_server is not None:
            self._gdb_server.shutdown()
            self._gdb_server = None

    def __del__(self):
        self.disconnect()

    ###############################################################################################
    # Properties

    @property
    def dconf(self) -> DottConf:
        return self._dconf

    @property
    def log(self) -> logging.Logger:
        return dottmi.utils.log

    @property
    def gdb_client(self) -> GdbClient:
        return self._gdb_client

    @property
    def gdb_client_is_connected(self) -> bool:
        return self._gdb_client_is_connected

    @property
    def symbols(self) -> BinarySymbols:
        return self._symbols

    @property
    def mem(self) -> TargetMem:
        if self._mem is None:
            raise DottException('No on-target memory access model set at this point!')
        return self._mem

    @mem.setter
    def mem(self, target_mem: TargetMem) -> None:
        if not isinstance(target_mem, TargetMem):
            raise DottException('mem has to be an instance of TargetMem')
        self._mem = target_mem

    @property
    def monitor(self) -> Monitor:
        return self._monitor

    @property
    def bp_handler(self) -> BreakpointHandler:
        return self._bp_handler

    @property
    def byte_order(self) -> str:
        return self._device_endianess

    @property
    def startup_delay(self) -> float:
        return self._startup_delay

    @startup_delay.setter
    def startup_delay(self, delay: float):
        self._startup_delay = delay

    @property
    def state_change_wait_secs(self) -> float:
        """
        Timeout in seconds used by wait_running and wait_halted members before raising a timeout exception.
        """
        return self._state_change_wait_secs

    @state_change_wait_secs.setter
    def state_change_wait_secs(self, secs: float) -> None:
        self._state_change_wait_secs = secs

    ###############################################################################################
    # General-purpose wrappers for on target command execution/evaluation

    def eval(self, expr: str, timeout: float | None = None) -> Union[int, float, bool, str, None]:
        """
        This method takes an expression to be evaluated. It is assumed that the target is halted when calling eval.
        An expression is every valid expression in the current program context such as registers, local or global
        variables or functions.
        For example:
          t.eval('$sp')  # returns content of stack pointer register
          t.eval('my_var')  # returns content of local variable my_var
          t.eval('*my_ptr_var')  # dereferences a local pointer variable
          t.eval('glob_var += 1')   # increments a global variable
          t.eval('my_func(99)')  # calls function my_fund with argument 99 and returns its result
        The eval function attempts to convert the result of the evaluation into a suitable python data type.

        Args:
            expr: The expression to be evaluation in the current context of the target.
            timeout: Optional timeout for eval call. Only needed if eval does not return because, e.g., hitting an exception.

        Returns:
            The evaluation result converted to a suitable Python data type.
        """
        res = self.exec(f'-data-evaluate-expression "{expr}"', timeout=timeout)
        if res is None:
            log.warning(f'Eval of {expr} did not succeed (return value is None)!')
            return None

        res = res['payload']['value']
        ret_val = cast_str(res)

        if '<optimized out>' in str(ret_val):
            log.warning(f'Accessed entity {expr} is optimized out in the target binary.')

        return ret_val

    def exec(self, cmd: str, timeout: float = None) -> Dict:
        return self._gdb_client.gdb_mi.write_blocking(cmd, timeout=timeout)

    def exec_noblock(self, cmd: str) -> int:
        return self._gdb_client.gdb_mi.write_non_blocking(cmd)

    def cli_exec(self, cmd: str, timeout: float | None = None) -> Dict:
        """
        Execute the given GDB CLI command and return MI result as dictionary. Note: This dictionary only contains
        command status information but NOT the (textual) result of the executed CLI command!
        To get the CLI command output, use cli_exec_data.

        Args:
            cmd: GBM CLI command to execute.
            timeout: Timeout as multiple (or fraction) of seconds.

        Returns: GDB CLI command result (status code) in dictionary.
        """
        return self._gdb_client.gdb_mi.write_blocking(f'-interpreter-exec console "{cmd}"', timeout=timeout)

    @requires_rt_ge_2
    def cli_exec_data(self, cmd: str, timeout: float | None = None) -> str:
        """
        Execute the given GDB CLI command and returns the result data as string. In contrast to cli_exec, this
        function does provide the full output of the CLI command (and not just the result).
        Note that using this function requires DOTT.NG runtime version 2 or higher.

        Args:
            cmd: GBM CLI command to execute.
            timeout: Timeout as multiple (or fraction) of seconds.

        Returns: GDB CLI command output as string.
        """
        res: Dict = self._gdb_client.gdb_mi.write_blocking(f'-dott-cli-exec "{cmd}"', timeout=timeout)
        return res['payload']['res'].strip()

    ###############################################################################################
    # Execution-related target commands

    def load(self, load_elf_file_name: str, symbol_elf_file_name: str | None = None, enable_flash: bool = False) -> None:
        self._load_elf_file_name = load_elf_file_name
        self._symbol_elf_file_name = symbol_elf_file_name

        if load_elf_file_name is not None:
            self.exec(f'-file-exec-file {self._load_elf_file_name}')
        if symbol_elf_file_name is not None:
            self.exec(f'-file-symbol-file')  # note: -file-symbol-file without arguments clears GDB's symbol table
            self.exec(f'-file-symbol-file {self._symbol_elf_file_name}')

        self.monitor.set_flash_device(self._device_name)
        self.monitor.enable_flash_download(enable_flash)

        if load_elf_file_name is not None:
            self.exec('-target-download')

    def reset(self, flush_reg_cache: bool = True) -> None:
        """
        Resets the target using the reset method provided by the debug monitor.
        Args:
            flush_reg_cache: Flushes GDB's register cache (default: True).
        """
        self.monitor.reset()
        if flush_reg_cache:
            self.reg_flush_cache()

    def cont(self) -> None:
        """
        Continues target execution.
        If the target is already running, the method returns without sending a command to the target or debugger.
        """
        with self._cv_target_state:
            if self._is_target_running:
                return

            self.exec('-exec-continue')
            self.wait_running()

    def ret(self, ret_val: Union[int, str] | None = None) -> None:
        """
        Returns from the function that is currently executed by the target. The remaining part of the function body
        is not executed. If a return value is provided, it is returned to the caller of the function.
        When the 'ret' functions returns, the target is in halted state.

        Args:
            ret_val: Return with ret_val from the currently executed function. The function's stack frame is discarded.
        """
        if ret_val is None:
            self.exec('-exec-return')
        else:
            # note: we are relying on the cli here since the MI command '-exec-return' does not support return values
            self.cli_exec(f'return {ret_val}')
        # Note: GDB's return implementation does not continue the target. Hence, no need for wait_running/halted.

    def finish(self) -> None:
        """
        Resumes the execution of the function that is currently executed by the target until the function is exited.
        When the 'finish' functions returns, the target is in halted state.
        """
        self.exec('-exec-finish')
        self.wait_running()
        self.wait_halted(expected_reason='function-finished')

    def halt(self, halt_in_it_block: bool = False) -> None:
        """
        Halts target execution.
        If the target is already halted, the method returns without sending a command to the target or debugger.

        Args:
            halt_in_it_block: A target halt may happen while the target is executing an IT block. In this case, calls
            to eval() will fail if they involved function calls (branches) and the target might become unresponsive.
            To avoid this type of situation, the halt command performs instruction stepping if it detects that the
            target was halted in an IT block. Instruction stepping is performed until the IT block is complete and then
            halt() returns.
            This single stepping is the default behavior of halt and can be deactivated by setting the halt_in_it_block
            to True. In this case, it is up to the user to check that the target is not halted in an IT block. If the
            user attempts to perform a function call, while the target is halted she either performs the same single
            instruction stepping strategy of backs up xPSR and zeros out the xPSR IT bits before performing a function
            call with eval(). After the function call, the xPSR has to be restored form the saved value.
        """
        with self._cv_target_state:
            if not self._is_target_running:
                return

            self.exec('-exec-interrupt --all')
            self.wait_halted(expected_reason='signal-received')

        if not halt_in_it_block:
            # check if we have halted in an IT block; if yes, do instruction stepping until we have left the IT block
            while self.reg_xpsr_in_it_block(self.eval(f'${self.monitor.xpsr_name()}')):
                self.step_inst()

    def step(self) -> None:
        """
        Performs source line stepping - one step at a time.
        """
        with self._cv_target_state:
            if self._is_target_running:
                raise RuntimeError('Target must be halted to perform source line stepping.')

            self.exec('-exec-step')
            # GDB state changes to running and then back to stopped
            self.wait_running()
            self.wait_halted(expected_reason='end-stepping-range')

    def step_inst(self):
        """
        Performs instruction stepping - one instruction at a time.
        """
        with self._cv_target_state:
            if self._is_target_running:
                raise RuntimeError('Target must be halted to perform source line stepping.')

            self.exec('-exec-step-instruction')
            # GDB state changes to running and then back to stopped
            self.wait_running()
            self.wait_halted(expected_reason='end-stepping-range')

    ###############################################################################################
    # Status-related target commands

    # This callback function is called from gdbmi response handler when a new notification
    # with a target status change notification is received.
    def _process_msg(self, msg: Dict):
        notify_msg: str = msg['message']
        notify_reason: str = msg['payload']['reason'] if 'reason' in msg['payload'] else None
        if 'stopped' in notify_msg:
            with self._cv_target_state:
                self._gdb_client.gdb_mi.debug_capture.record(f'[TARGET STOPPED] {msg}; '
                                                             f'Thread: {threading.current_thread().name}')
                self._is_target_running = False
                self._target_state_change_reason = notify_reason
                self._gdb_client.gdb_mi.debug_capture.record(f'[TARGET STOPPED DONE] {threading.current_thread().name}')
            while self._wait_halted_cnt > 0:
                with self._cv_target_state:
                    self._cv_target_state.notify_all()
                time.sleep(.0001)  # pass control to other threads which decrement self._wait_halted_cnt

        elif 'running' in notify_msg:
            with self._cv_target_state:
                self._gdb_client.gdb_mi.debug_capture.record(f'[TARGET RUNNING] {msg}; '
                                                             f'Thread: {threading.current_thread().name}')
                self._is_target_running = True
                self._target_state_change_reason = notify_reason
                self._gdb_client.gdb_mi.debug_capture.record(f'[TARGET RUNNING DONE] {threading.current_thread().name}')
            while self._wait_running_cnt > 0:
                with self._cv_target_state:
                    self._cv_target_state.notify_all()
                time.sleep(.0001)   # pass control to other threads which decrement self._wait_running_cnt
        else:
            log.warning(f'Unhandled notification: {notify_msg}')

    def is_running(self) -> bool:
        """
        Use this function to check if the target is running or not.

        Returns:
            Returns True if the target is running, false otherwise.
        """
        with self._cv_target_state:
            return self._is_target_running

    def is_halted(self) -> bool:
        """
        Use this function to check if the target is halted or not.

        Returns:
            Returns True if the target is halted, false otherwise.
        """
        with self._cv_target_state:
            return not self._is_target_running

    def wait_halted(self, wait_secs: float | None = None, expected_reason: str | None = None) -> None:
        """
        Wait until target is halted. The wait_halted command is typically not needed in user code as halt ensures that
        the target is halted when it returns.

        Args:
            wait_secs: Number of seconds to wait before a DottException is thrown.
            expected_reason: Expected halt reason.
        """
        if not wait_secs:
            wait_secs = self._state_change_wait_secs

        with self._cv_target_state:
            if self._is_target_running:
                self._gdb_client.gdb_mi.debug_capture.record(f'[WAIT_HALTED] {threading.current_thread().name}')
                self._wait_halted_cnt += 1
                self._cv_target_state.wait_for(self.is_halted, wait_secs)
                self._wait_halted_cnt -= 1
            else:
                self._gdb_client.gdb_mi.debug_capture.record(f'[WAIT_HALTED FALLTHROUGH] {threading.current_thread().name}')
            if self._is_target_running:
                self._gdb_client.gdb_mi.debug_capture.record(f'[WAIT_HALTED FAILED] {threading.current_thread().name}')
                self._gdb_client.gdb_mi.debug_capture.dump()
                raise DottException(f'Target did not change to "halted" state within {wait_secs} seconds.'
                                    f'Thread: {threading.current_thread().name}')

            if expected_reason is not None:
                if self._target_state_change_reason != expected_reason:
                    log.warning('Target stopped with reason "%s" instead of expected reason "%s".',
                                self._target_state_change_reason, expected_reason)
                    stack_trace = traceback.extract_stack()

                    for frm in stack_trace:
                        if 'site-packages' not in frm.filename:
                            log.warning('   %s (line: %d): %s', frm.filename, frm.lineno, frm.line)

    def wait_running(self, wait_secs: float | None = None) -> None:
        """
        Wait until target is running. The wait_running command is typically not needed in user code as cont ensures that
        the target is running when it returns.

        Args:
            wait_secs: Number of seconds to wait before a DottException is thrown.
        """
        if not wait_secs:
            wait_secs = self._state_change_wait_secs

        with self._cv_target_state:
            if not self._is_target_running:
                self._gdb_client.gdb_mi.debug_capture.record(f'[WAIT_RUNNING] {threading.current_thread().name}')
                self._wait_running_cnt += 1
                self._cv_target_state.wait_for(self.is_running, wait_secs)
                self._wait_running_cnt -= 1
            else:
                self._gdb_client.gdb_mi.debug_capture.record(f'[WAIT_RUNNING FALLTHROUGH] {threading.current_thread().name}')
            if not self._is_target_running:
                self._gdb_client.gdb_mi.debug_capture.record(f'[WAIT_RUNNING FAILED] {threading.current_thread().name}')
                self._gdb_client.gdb_mi.debug_capture.dump()
                raise DottException(f'Target did not change to "running" state within {wait_secs} seconds.'
                                    f'Thread: {threading.current_thread().name}')

    ###############################################################################################
    # Breakpoint-related target commands

    def bp_clear_all(self) -> None:
        self.cli_exec('dott-bp-nostop-delete')
        self.exec('-break-delete')
        self.monitor.clear_all_breakpoints()

    def bp_get_count(self) -> int:
        res = self.exec('-break-list')
        cnt = int(res['payload']['BreakpointTable']['nr_rows'])
        return cnt

    def _bp_get_list(self) -> []:
        res = self.exec('-break-list')
        bp_list = res['payload']['BreakpointTable']['body']
        return bp_list

    ###############################################################################################
    # Register-related target commands

    def reg_get_content(self, fmt: str = 'x', regs: List | None = None) -> Dict:
        if regs is None:
            regs = []
        res = self.exec('-data-list-register-values --skip-unavailable %s %s' % (fmt, ' '.join(str(r) for r in regs)))
        return res['payload']['register-values']

    def reg_get_names(self, regs: List | None = None) -> Dict:
        if regs is None:
            regs = []
        res = self.exec('-data-list-register-names %s' % ' '.join(str(r) for r in regs))
        return res['payload']['register-names']

    def reg_get_changed(self) -> Dict:
        res = self.exec('-data-list-changed-registers')
        return res['payload']['changed-registers']

    def reg_flush_cache(self) -> None:
        """
        Flush GDB's internal register cache. This command is useful if the target's state was changed in a way that
        is outside the control/awareness of GDB.
        """
        self.cli_exec('flushregs')

    def reg_xpsr_to_str(self, xpsr: int) -> str:
        """
        Decodes the given xPSR value and returns a human-readable string (spanning multiple lines) which describes the
        xPSR content of an Arm Cortex-M MCU.

        Args:
            xpsr: xPSR content. Obtain the value with Target::eval('$xpsr') for Segger or  Target::eval('$xPSR')
            for OpenOCD.

        Returns: Multi-line string with human-readable description of xPSR content. Ready for printing/logging.
        """
        ret: str = f'xPSR: 0b{xpsr:032b} (0x{xpsr:08x})' + os.linesep
        ret += f'negative (N):. ..... {(xpsr & (0b1 << 31)) >> 31}' + os.linesep
        ret += f'zero (Z): .......... {(xpsr & (0b1 << 30)) >> 30}' + os.linesep
        ret += f'carry (C): ......... {(xpsr & (0b1 << 29)) >> 29}' + os.linesep
        ret += f'overflow (V): ...... {(xpsr & (0b1 << 28)) >> 28}' + os.linesep
        ret += f'cumulative sat. (Q): {(xpsr & (0b1 << 27)) >> 27}' + os.linesep
        ret += f'if/then/else (IT): . {(xpsr & (0b11 << 25)) >> 25:02b}     (IT[1:0)' + os.linesep
        ret += f'thumb state (T): ... {(xpsr & (0b1 << 24)) >> 24}' + os.linesep
        ret += f'gt or equal (GE): .. {(xpsr & (0b1111 << 16)) >> 16}' + os.linesep
        ret += f'if/then/else (IT): . {(xpsr & (0b111111 << 10)) >> 10:06b} (IT[7:2)' + os.linesep

        return ret

    def reg_xpsr_in_it_block(self, xpsr: int) -> bool:
        """
        Returns True if the provided xpsr value indicates that the Arm Cortex-M processor currently is executing
        an if/then instruction (i.e., is in an IT block with IT bits in xPSR set).

        Args:
            xpsr: xPSR content. Obtain the value with Target::eval('$xpsr') for Segger or  Target::eval('$xPSR')
            for OpenOCD.

        Returns: Returns True if target is executing an IT block, false otherwise.
        """
        if (xpsr & (0b11 << 25)) >> 25 > 0 or (xpsr & (0b111111 << 10)) >> 10 > 0:
            return True
        return False
