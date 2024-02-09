/*
 * main implementation: use this 'C' sample to create your own application
 *
 */
#include "S32K144.h"
#include "stdbool.h"
#include "testhelpers.h"
#include "quicksort.h"

#if defined (__ghs__)
    #define __INTERRUPT_SVC  __interrupt
    #define __NO_RETURN _Pragma("ghs nowarning 111")
#elif defined (__ICCARM__)
    #define __INTERRUPT_SVC  __svc
    #define __NO_RETURN _Pragma("diag_suppress=Pe111")
#elif defined (__GNUC__)
    #define __INTERRUPT_SVC  __attribute__ ((interrupt ("SVC")))
    #define __NO_RETURN
#else
    #define __INTERRUPT_SVC
    #define __NO_RETURN
#endif

int counter, accumulator = 0, limit_value = 1000000;
volatile uint32_t global_data = 0xdeadbeef;

int main(void) {
    counter = 0;

    DOTT_test_hook();

	while(true) {
		global_data++;

		/* quicksort exmaple */
	 	int arr[] = { 4, 3, 5, 2, 1, 3, 2, 3 };
		int n = 8;
		quickSort(arr, 0, n - 1);
		DOTT_LABEL_SAFE("QS_MAIN_DONE");

        counter++;
        if (counter >= limit_value) {
            __asm volatile ("svc 0");
            counter = 0;
        }
	}

	/* to avoid the warning message for GHS and IAR: statement is unreachable*/
    __NO_RETURN
    return 0;
}

__INTERRUPT_SVC void SVC_Handler() {
    accumulator += counter;
}
