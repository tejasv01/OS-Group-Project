#ifndef _PSTAT_H_
#define _PSTAT_H_

#include "param.h"

// Process statistics structure for MLFQ inspection via getpinfo()
struct pstat {
  int inuse[NPROC];     // 1 if process slot is active, 0 if unused
  int pid[NPROC];       // Process ID
  int priority[NPROC];  // Current MLFQ priority level (0: highest, 3: lowest)
  int ticks[NPROC][4];  // Accumulated CPU ticks at each priority level (Q0 to Q3)
};

#endif
