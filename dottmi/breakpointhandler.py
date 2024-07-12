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

import threading
from typing import Dict

from dottmi.breakpoint import Breakpoint
from dottmi.gdb_mi import NotifySubscriber
from dottmi.utils import log


# -------------------------------------------------------------------------------------------------
class BreakpointHandler(NotifySubscriber):
    def __init__(self) -> None:
        NotifySubscriber.__init__(self, name='BreakpointHandler', process_in_thread=True)
        self._breakpoints: Dict = {}
        self._bp_lock = threading.Lock()

    def add_bp(self, bp: Breakpoint) -> None:
        with self._bp_lock:
            self._breakpoints[bp.num] = bp

    def remove_bp(self, bp: Breakpoint) -> None:
        with self._bp_lock:
            self._breakpoints.pop(bp.num)

    def _process_msg(self, msg: Dict) -> None:
        if 'reason' in msg['payload']:
            payload = msg['payload']
            if payload['reason'] == 'breakpoint-hit':
                bp_num = int(payload['bkptno'])
                with self._bp_lock:
                    if bp_num in self._breakpoints:
                        self._breakpoints[bp_num].reached_internal(payload)
                    else:
                        log.warn(f'Breakpoint with number {bp_num} not found in list of known breakpoints.')
            else:
                log.error(f'stop notification received with wrong reason: {payload["reason"]}')
