*** Settings ***
Library      dottRF.py         WITH NAME     dott
*** Test Cases ***
simple function calls
    ${RES}=          dott.eval_on_target  example_NoArgs()
    Should be equal  42                   ${RES}
    ${RES}=          dott.eval_on_target  example_NoArgsStatic()
    Should be equal  42                   ${RES}
    ${RES}=          dott.eval_on_target  example_Addition(31, 11)
    Should be equal  42                   ${RES}


usage of memory management
    dott.alloc_type   uint32_t             val=${9}                     var_name=$a
    dott.alloc_type   uint32_t             val=${12}                    var_name=$b
    ${RES}=           dott.eval_on_target  example_AdditionPtr($a, $b)
    Should be equal   21                   ${RES}
