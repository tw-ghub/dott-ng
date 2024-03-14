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

from dottmi.dott import dott

class TestTargetCreation:

    # This test demonstrates the setting of a function pointer via DOTT/GDB and via code. Differences are
    # in the 'smart' handling of the Thumb bit (required for function pointers) by GDB.
    def test_function_pointer(self, target_load, target_reset):
        dt = dott().target

        res = dt.eval('example_FunctionPointers()')
        assert res == 30

        # When setting the function pointer directly to an address, the lest significant bit needs to be
        # set to make the function pointer valid in Thumb mode.
        ptr = dt.eval('&example_GetA')
        dt.eval(f'func_a = {ptr | 0x00000001}')
        res = dt.eval('example_FunctionPointers()')
        assert res == 62

        # The function pointer can be (re-)set to NULL via direct assignment
        dt.eval(f'func_a = {0x0}')
        res = dt.eval('example_FunctionPointers()')
        assert res == 30

        # When setting the function pointer via a setter function (which takes a function pointer parameter)
        # GDB automatically sets the thumb bit.
        dt.eval(f'reg_func_ptr_param({ptr})')
        res = dt.eval('example_FunctionPointers()')
        assert res == 62

        # IMPORTANT Note:
        # When attempting to set the function pointer to NULL (0x0) via a setter function which takes a function pointer
        # argument, GDB also sets the thumb bit. For example, in dt.eval(f'reg_func_ptr_param(0x0)') GDB automatically
        # sets the Thumb bit, which means that the function pointer is set to 0x1 instead of the expected 0x0.
        # This is documented in https://sourceware.org/git/?p=binutils-gdb.git;a=blob;f=gdb/arm-tdep.c  which states:
        #        /* If the argument is a pointer to a function, and it is a
        #           Thumb function, create a LOCAL copy of the value and set
        #           the THUMB bit in it.  */
        #
        # To still be able to set the function pointer to 0x0 (NULL), the following workaround is recommended:
        # When setting the function pointer directly to NULL (instead of using the setter function), either
        # with eval() or mem.write(), GDB does NOT automatically set the Thumb bit.

        dt.eval(f'reg_func_ptr_param({0x0})')
        assert dt.eval(f'func_a') == 0x1  # thumb bit was set by GBB

        # The function pointer can be (re-)set to NULL via direct assignment.
        dt.eval(f'func_a = {0x0}')
        assert dt.eval('func_a') == 0x0  # thumb bit was NOT set by GBB
        res = dt.eval('example_FunctionPointers()')
        assert res == 30

        # When setting the function pointer via 'hardcoded' setter function, GCC already sets the thumb bit.
        dt.eval(f'reg_func_ptr_a()')
        assert (dt.eval('&example_GetA') & 0x1) == 0x0  # function address has LSBit == 0
        assert (dt.eval('func_a') & 0x1) == 0x1  # function pointer set
        res = dt.eval('example_FunctionPointers()')
        assert res == 62

        # Also setting to NULL via 'hardcoded' setter function actually sets the function pointer to NULL (0x0).
        dt.eval(f'reg_func_ptr_null()')
        res = dt.eval('example_FunctionPointers()')
        assert res == 30
