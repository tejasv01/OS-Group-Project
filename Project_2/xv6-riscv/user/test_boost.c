#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

static int
spin_work(int loops)
{
  volatile int x = 0;
  for (int i = 0; i < loops; i++) {
    x += i * i;
  }
  return x;
}

int
main(int argc, char *argv[])
{
  struct pstat ps;
  int pid = fork();

  if (pid < 0) {
    printf("FAIL: fork failed\n");
    exit(1);
  }

  if (pid == 0) {
    // Child burns CPU continuously
    while (1) {
      if (spin_work(5000000) == 123456789)
        printf("rare\n");
    }
    exit(0);
  }

  printf("=== Test 8: Priority Boosting (Starvation Prevention) ===\n");
  printf("Monitoring child PID %d demotion and subsequent boost back to Q0...\n", pid);

  int reached_q3 = 0;
  int boosted = 0;
  int initial_q0_ticks = 0;

  // Monitor child over time
  for (int sample = 0; sample < 150; sample++) {
    pause(1); // Sleep 1 tick to allow child to execute

    if (getpinfo(&ps) == 0) {
      for (int i = 0; i < NPROC; i++) {
        if (ps.inuse[i] && ps.pid[i] == pid) {
          int cur_pri = ps.priority[i];

          if (!reached_q3 && cur_pri == 3) {
            reached_q3 = 1;
            initial_q0_ticks = ps.ticks[i][0];
            printf("  Child PID %d reached Q3 | Ticks: [Q0:%d, Q1:%d, Q2:%d, Q3:%d]\n",
                   pid, ps.ticks[i][0], ps.ticks[i][1], ps.ticks[i][2], ps.ticks[i][3]);
            printf("  Waiting for periodic priority boost to restore child to Q0...\n");
          } else if (reached_q3) {
            // Once reached Q3, normal execution only stays in Q3.
            // If priority becomes < 3 or Q0 ticks increase, boost has fired!
            if (cur_pri < 3 || ps.ticks[i][0] > initial_q0_ticks) {
              boosted = 1;
              printf("  PASS: Priority boost detected!\n");
              printf("        Process was demoted to Q3, now at Q%d (Q0 ticks grew from %d to %d)\n",
                     cur_pri, initial_q0_ticks, ps.ticks[i][0]);
              printf("        Current Ticks: [Q0:%d, Q1:%d, Q2:%d, Q3:%d]\n",
                     ps.ticks[i][0], ps.ticks[i][1], ps.ticks[i][2], ps.ticks[i][3]);
              if (ps.ticks[i][3] > 0 && ps.ticks[i][2] > 0) {
                printf("  PASS: Historical tick statistics were preserved across boost!\n");
              }
              break;
            }
          }
          break;
        }
      }
    }
    if (boosted)
      break;
  }

  kill(pid);
  wait(0);

  if (boosted) {
    printf("PASS: Test 8 (Priority Boosting) successfully verified!\n");
    exit(0);
  } else {
    printf("FAIL: Priority boost not detected within monitoring window\n");
    exit(1);
  }
}
