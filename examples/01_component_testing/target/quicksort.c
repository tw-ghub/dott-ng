#include <stdint.h>
#include <stdbool.h>


void __attribute__((noinline)) swap(int *a, int *b)
{
  int t = *a;
  *a = *b;
  *b = t;
}


bool __attribute__((noinline)) is_le(int a, int b)
{
	bool ret_val = false;
	
	if (a <= b) {
		ret_val = true;
	}
	
	return ret_val;
}



int partition(int array[], int low, int high)
{
  int pivot = array[high];
  int i = (low - 1);

  for (int j = low; j < high; j++) {
    if (is_le(array[j], pivot)) {
      i++;
      swap(&array[i], &array[j]);
    }
  }

  swap(&array[i + 1], &array[high]);
  return (i + 1);
}


/*
 * Simple recursive QS implementation - just for demo purposes.
 */
void quickSort(int array[], int low, int high)
{
  if (low < high) {
    int pi = partition(array, low, high);
    quickSort(array, low, pi - 1);
    quickSort(array, pi + 1, high);
  }
}