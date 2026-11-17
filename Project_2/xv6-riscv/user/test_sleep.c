#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

int
main(int argc, char *argv[])
{
  struct pstat ps;
  int pid = getpid();
  int ticks_before = 0;
  int ticks_after = 0;
  int pri_before = 0;
  int pri_after = 0;

  printf("=== Test: Sleeping and Waking (Tick Accounting) ===\n");

  // Read ticks before sleep
  if (getpinfo(&ps) < 0) {
    printf("FAIL: getpinfo failed\n");
    exit(1);
  }

  for (int i = 0; i < NPROC; i++) {
    if (ps.inuse[i] && ps.pid[i] == pid) {
      pri_before = ps.priority[i];
      ticks_before = ps.ticks[i][0] + ps.ticks[i][1] + ps.ticks[i][2] + ps.ticks[i][3];
      printf("Before sleep: PID %d Priority=Q%d Total_CPU_Ticks=%d\n",
             pid, pri_before, ticks_before);
      break;
    }
  }

  // Sleep for 15 timer ticks using pause()
  printf("Process going to sleep for 15 ticks via pause(15)...\n");
  pause(15);
  printf("Process woke up successfully!\n");

  // Read ticks after sleep
  if (getpinfo(&ps) < 0) {
    printf("FAIL: getpinfo failed\n");
    exit(1);
  }

  for (int i = 0; i < NPROC; i++) {
    if (ps.inuse[i] && ps.pid[i] == pid) {
      pri_after = ps.priority[i];
      ticks_after = ps.ticks[i][0] + ps.ticks[i][1] + ps.ticks[i][2] + ps.ticks[i][3];
      printf("After sleep: PID %d Priority=Q%d Total_CPU_Ticks=%d (Q0=%d, Q1=%d, Q2=%d, Q3=%d)\n",
             pid, pri_after, ticks_after,
             ps.ticks[i][0], ps.ticks[i][1], ps.ticks[i][2], ps.ticks[i][3]);
      break;
    }
  }

  int diff = ticks_after - ticks_before;
  printf("CPU ticks accumulated during 15-tick sleep period: %d\n", diff);

  // If sleep time were erroneously counted as CPU time, diff would be >= 15.
  // In a correct scheduler, diff should be 0 or at most 1 (for trap return).
  if (diff < 5) {
    printf("PASS: Sleeping time was NOT counted as CPU execution time!\n");
    printf("PASS: Process successfully resumed and scheduled after waking!\n");
    exit(0);
  } else {
    printf("FAIL: Sleep time incorrectly counted as CPU execution time (diff=%d)\n", diff);
    exit(1);
  }
}
