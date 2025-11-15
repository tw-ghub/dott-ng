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

import json
import multiprocessing
import queue
import socket
import threading
import time
import warnings
from abc import *
from typing import List, Union, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from dottmi.target import Target

from dottmi.dott import dott
from dottmi.dottexceptions import DottException
from dottmi.gdb_mi import GdbMiContext
from dottmi.gdb_shared import BpMsg, BpSharedConf
from dottmi.utils import log, cast_str, ExceptionPropagator


# Abstract base class defining common methods for all breakpoints.
class Breakpoint(ABC):

    def __init__(self, location: [str, int], target: Target = None) -> None:
        """
        Create a new breakpoint at a given program location.

        Args:
            location: Either a symbol name (str), an address (int) or a GDB location (str) which may be an address (prefixed with *) or a line offset (+/-).
            target: The target the breakpoint is created for (default target is used if no target is specified).
        """
        self._dott_target: Target = target
        if self._dott_target is None:
            self._dott_target: Target = dott().target  # Note: _target used by Thread; InterceptPoint inherits from it

        if isinstance(location, str):
            if not location.startswith(('+', '-', '*')):  # GDB locations may be an address (*) or a line offset (+/-) instead of a symbol
                if not self._dott_target.symbols.exists(location):
                    raise DottException(f'No symbol "{location}" found in target binary symbols.')
        elif isinstance(location, int):
            location = f'*{location}'
        else:
            raise ValueError('Parameter location is not of type str or int.')

        self._location: str = location
        self._hits: int = 0
        self._num: int = -1

    @property
    def num(self) -> int:
        """
        The breakpoint number.
        """
        return self._num

    @num.setter
    def num(self, num: int) -> None:
        self._num = num

    @abstractmethod
    def reached(self) -> None:
        """
        Executed when the breakpoint is reached.
        """
        pass

    @abstractmethod
    def wait_complete(self) -> None:
        """
        This method allows to block the execution of the Python test program until the breakpoint has been hit.
        """
        pass

    @abstractmethod
    def delete(self) -> None:
        """
        Deletes the breakpoint.
        """
        pass

    @abstractmethod
    def exec(self, cmd: str) -> None:
        """
        Execute a GDB-MI command in blocking mode.

        Args:
            cmd: GDB-MI command to be executed.
        """
        pass

    @abstractmethod
    def eval(self, cmd: str) -> None:
        """
        This method takes an expression to be evaluated. See target.eval() for details.

        Args:
            cmd: Expression to be evaluated.
        """
        pass

    @abstractmethod
    def ret(self, ret_val: Union[int, str] = None) -> None:
        """
        Return from the currently executed target function.

        Args:
            ret_val: Value to be returned to the calling function.
        """
        pass

    def get_location(self) -> str:
        """
        Get the location of the breakpoint.

        Returns: The breakpoint location.
        """
        return self._location

    def get_hits(self) -> int:
        """
        Returns the number of this for the breakpoint.

        Returns: The number of hits the breakpoint has seen.
        """
        return self._hits


# -------------------------------------------------------------------------------------------------
class HaltPoint(Breakpoint):
    def __init__(self, location: str, temporary: bool = False, target: Target = None) -> None:
        super().__init__(location, target)
        self._bp_info: Dict | None = None
        self._q: queue.Queue = queue.Queue()

        args = ''
        if temporary:
            args += '-t'

        try:
            msg = self._dott_target.exec(f'-break-insert {args} {location}')
        except Exception as ex:
            log.error('Creating breakpoint failed.')
            log.exception(ex)
            raise ex

        if 'payload' in msg:
            payload = msg['payload']
            if 'bkpt' in payload:
                self._bp_info = payload['bkpt']
        if self._bp_info is None:
            raise Exception('Invalid breakpoint information.')

        self._num = int(self._bp_info['number'])
        self._addr = self._bp_info['addr']

        # add breakpoint to breakpoint handler
        self._dott_target.bp_handler.add_bp(self)

    # allow the test thread to wait for a breakpoint event to occur
    def wait_complete(self, timeout: float | None = None) -> None:
        try:
            if not timeout:
                timeout = self._dott_target.state_change_wait_secs
            self._q.get(block=True, timeout=timeout)
        except queue.Empty:
            self._dott_target.gdb_client.gdb_mi.debug_capture.dump()
            raise TimeoutError(f"Timeout {timeout}s) while waiting to reach halt point at {self._location}.") from None

    def reached_internal(self, payload=None) -> None:
        self._hits += 1
        try:
            self._dott_target.wait_halted(expected_reason='breakpoint-hit')
        except DottException as exc:
            log.warn('Target did not change to state halted!')
            ExceptionPropagator.propagate_exception(exc)
        try:
            self.reached()
        except Exception as exc:
            ExceptionPropagator.propagate_exception(exc)
        # queue is used to notify one potentially waiting thread
        self._q.put(None, block=False)

    def reached(self) -> None:
        # to be implemented by sub-class as needed
        pass

    def eval(self, cmd: str) -> Union[int, float, bool, str]:
        # a halt breakpoint can rely on normal DOTT exec command
        return self._dott_target.eval(cmd)

    def exec(self, cmd: str) -> None:
        # a halt breakpoint can rely on normal DOTT exec command
        self._dott_target.exec(cmd)

    def ret(self, ret_val: Union[int, str] = None):
        # a halt breakpoint can rely on normal DOTT exec command
        self._dott_target.ret(ret_val)

    def delete(self) -> None:
        self._dott_target.exec(f'-break-delete {self._num}')


# -------------------------------------------------------------------------------------------------
class Barrier(HaltPoint):
    def __init__(self, location: str, temporary: bool = False, parties: int = 1, target: Target = None) -> None:
        if parties != 1:
            raise DottException('DOTT barrier implementation only supports 1 party (thread) '
                                'to wait for a location to be reached.')

        HaltPoint.__init__(self, location, temporary, target)

    def reached(self) -> None:
        self._dott_target.cont()

    def cont_when_reached(self, timeout: int = None) -> None:
        return self.wait_complete(timeout)


# -------------------------------------------------------------------------------------------------
class InterceptPointCmds(Breakpoint):
    def __init__(self, location: str, commands: List, target: Target = None) -> None:
        super().__init__(location, target)
        # serialize function name and commands using JSON and supply them to custom GDB command
        com = json.dumps([location] + commands)
        com = com.replace('"', '\\"')
        self._dott_target.exec(f'dott-bp-nostop-cmd {com}')

    def wait_complete(self, timeout: float = None) -> None:
        warnings.warn('You can not wait for the completion of a intercept breakpoint.')

    def exec(self, cmd: str) -> None:
        warnings.warn('A command intercept point only executes the commands set in the constructor.')

    def eval(self, cmd: str) -> None:
        warnings.warn('A command intercept point only executes the commands set in the constructor.')

    def ret(self, ret_val: Union[int, str] = None):
        warnings.warn('A command intercept point only executes the commands set in the constructor.')

    def reached(self) -> None:
        warnings.warn('A command intercept point only executes the commands set in the constructor.')

    def delete(self) -> None:
        self._dott_target.cli_exec(f'dott-bp-nostop-delete {self._location}')

    def get_hits(self) -> None:
        warnings.warn('Unable to report hits for intercept point with command list.')


# -------------------------------------------------------------------------------------------------
class InterceptPoint(threading.Thread, Breakpoint):
    _intercept_points = []

    @staticmethod
    def _register(ipoint: 'InterceptPoint') -> None:
        InterceptPoint._intercept_points.append(ipoint)

    @staticmethod
    def _unregister(ipoint: 'InterceptPoint') -> None:
        InterceptPoint._intercept_points.remove(ipoint)

    @staticmethod
    def delete_all() -> None:
        # iterate over a copy
        for item in InterceptPoint._intercept_points[:]:
            item.delete()
        if len(InterceptPoint._intercept_points) != 0:
            log.warning('Not all Intercept points were deleted!')

    # ---------------------------------------------------------------------------------------------
    def __init__(self, location: str, target: Target = None) -> None:
        Breakpoint.__init__(self, location, target)
        threading.Thread.__init__(self, name='InterceptPoint')
        self._running: bool = False
        self._event: multiprocessing.Event = multiprocessing.Event()
        self._event.clear()

        # open server socket for incoming connection from custom GDB command
        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_sock.bind(('127.0.0.1', BpSharedConf.GDB_CMD_SERVER_PORT))
        srv_sock.listen(1)

        # call custom GDB command
        self._dott_target.cli_exec(f'dott-bp-nostop-tcp {self._location}')

        self._sock, addr = srv_sock.accept()
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        srv_sock.close()

        InterceptPoint._register(self)
        self.start()

    def exec(self, cmd: str) -> None:
        msg = BpMsg(BpMsg.MSG_TYPE_EXEC, payload=bytes(cmd, 'ascii'))
        msg.send_to_socket(self._sock)

        res = BpMsg.read_from_socket(self._sock)
        if res.get_type() == BpMsg.MSG_TYPE_EXCEPT:
            raise RuntimeError(f'Execution of command "{cmd}" in breakpoint context failed. '
                               f'{res.get_payload().decode("ascii")}')

    def eval(self, cmd: str) -> Union[int, float, str]:
        msg = BpMsg(BpMsg.MSG_TYPE_EVAL, payload=bytes(cmd, 'ascii'))
        msg.send_to_socket(self._sock)

        res = BpMsg.read_from_socket(self._sock)
        if res.get_type() == BpMsg.MSG_TYPE_EXCEPT:
            raise RuntimeError(f'Execution of command "{cmd}" in breakpoint context failed. '
                               f'{res.get_payload().decode("ascii")}')
        res = cast_str(res.get_payload())

        if '<optimized out>' in str(res):
            log.warning(f'Accessed entity {cmd} is optimized out in the binary.')

        return res

    def ret(self, ret_val: Union[int, str] = None) -> None:
        if ret_val is not None:
            self.exec(f'return {ret_val}')
        else:
            self.exec(f'return')

    def reached(self) -> None:
        # to be implemented by sub-class as needed
        pass

    def _signal_complete(self) -> None:
        self._event.set()

    def wait_complete(self, timeout: float = None) -> None:
        timeout_override = False

        # If no timeout was given set a reasonable high override timeout
        # to prevent from getting stuck if a breakpoint is not reached.
        if timeout is None:
            timeout_override = True
            timeout = 20
        wait_ok = self._event.wait(timeout)
        self._event.clear()

        if (not wait_ok) and timeout_override:
            raise TimeoutError(f'InterceptPoint {self._location} not reached after override timeout of {timeout}secs.')
        elif (not wait_ok) and (not timeout_override):
            raise TimeoutError(f'InterceptPoint {self._location} not reached after timeout of {timeout}secs.')

    def run(self) -> None:
        self._running = True

        while self._running:
            # wait for 'breakpoint hit' message
            try:
                msg = BpMsg.read_from_socket(self._sock)
                if msg.get_type() != BpMsg.MSG_TYPE_HIT:
                    log.warning(f'Received breakpoint message of type {msg.get_type()} while waiting for type "HIT"')
                self._hits += 1
            except ConnectionAbortedError:
                log.warning(f'Breakpoint {self._location}: connection aborted')
                self.delete()
                break
            except ConnectionResetError:
                log.warning(f'Breakpoint {self._location}: connection reset')
                self.delete()
                break
            except Exception as ex:
                if self._running:
                    log.warning(f'Breakpoint {self._location}: exception: {str(ex)}')
                    self.delete()
                else:
                    # Got a socket error while no longer supposed to be running (i.e., during delete).
                    # We don't need to do anything about this.
                    pass
                break

            try:
                self._dott_target.gdb_client.gdb_mi.context.acquire_context(self, GdbMiContext.BP_INTERCEPT)
                self.reached()
            except Exception as ex:
                ExceptionPropagator.propagate_exception(ex)
            finally:
                self._dott_target.gdb_client.gdb_mi.context.release_context(self)

            msg = BpMsg(BpMsg.MSG_TYPE_FINISH_CONT)
            msg.send_to_socket(self._sock)
            time.sleep(0.1)  # release control. preference would be handshake once target is running again.

            # notify threads which are potentially waiting for completion of this breakpoint
            self._signal_complete()

    def delete(self) -> None:
        try:
            if self._running:
                self._running = False
                self._dott_target.cli_exec(f'dott-bp-nostop-delete {self._location}', timeout=1)
                InterceptPoint._unregister(self)
                self._sock.close()
                self.join(timeout=1)
        except:
            pass

    def __del__(self):
        self.delete()
