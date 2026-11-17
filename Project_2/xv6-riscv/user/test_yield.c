#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

int
main(int argc, char *argv[])
{
  struct pstat ps;
  int pid = getpid();
  int initial_pri = -1;

  printf("=== Test: Voluntary Yield (Priority Retention) ===\n");

  // Synchronize to the beginning of a fresh tick window
  pause(1);

  // Read initial priority
  if (getpinfo(&ps) < 0) {
    printf("FAIL: getpinfo failed\n");
    exit(1);
  }

  for (int i = 0; i < NPROC; i++) {
    if (ps.inuse[i] && ps.pid[i] == pid) {
      initial_pri = ps.priority[i];
      printf("Process PID %d initial priority: Q%d\n", pid, initial_pri);
      break;
    }
  }

  // Yield CPU repeatedly (e.g. 50 times) without consuming a full timer tick
  printf("Yielding CPU voluntarily 50 times...\n");
  for (int i = 0; i < 50; i++) {
    yield();
  }

  // Check priority after yielding
  if (getpinfo(&ps) < 0) {
    printf("FAIL: getpinfo failed\n");
    exit(1);
  }

  int current_pri = -1;
  for (int i = 0; i < NPROC; i++) {
    if (ps.inuse[i] && ps.pid[i] == pid) {
      current_pri = ps.priority[i];
      printf("Process PID %d after 50 yields: Priority=Q%d (Ticks: Q0=%d, Q1=%d, Q2=%d, Q3=%d)\n",
             pid, current_pri,
             ps.ticks[i][0], ps.ticks[i][1], ps.ticks[i][2], ps.ticks[i][3]);
      break;
    }
  }

  if (current_pri == initial_pri) {
    printf("PASS: Process retained its priority Q%d after voluntary yields!\n", current_pri);
    exit(0);
  } else {
    printf("FAIL: Process priority changed from Q%d to Q%d on voluntary yield\n",
           initial_pri, current_pri);
    exit(1);
  }
}
