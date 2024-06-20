# vim: set tabstop=4 expandtab :
###############################################################################
#   Copyright (c) 2019-2021 ams AG
#   Copyright (c) 2022 Thomas Winkler <thomas.winkler@gmail.com>
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

from dottmi.target_mem import TypedPtr
from dottmi.utils import DottConvert
from dottmi.dott import DottConf, dott
from dottmi.breakpoint import HaltPoint, InterceptPoint, InterceptPointCmds


_dott = dott()
_target = _dot.target


def Eval_on_target(c_call):
    return _target.eval('example_NoArgs()')

def Alloc_type(type_name, **kwargs):
    _target.mem.alloc_type(type_name, var_name=var_name)
