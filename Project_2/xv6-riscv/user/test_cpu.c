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
  printf("=== Test 4: CPU-Intensive Demotion (Q0 -> Q1 -> Q2 -> Q3) ===\n");

  int pid = fork();
  if (pid < 0) {
    printf("FAIL: fork failed\n");
    exit(1);
  }

  if (pid == 0) {
    // Child burns CPU continuously
    while (1) {
      if (spin_work(10000000) == 123456789)
        printf("rare\n");
    }
    exit(0);
  }

  // Parent monitors child process demotion through queues
  struct pstat ps;
  int last_pri = -1;
  int q0_seen = 0, q1_seen = 0, q2_seen = 0, q3_seen = 0;

  for (int sample = 0; sample < 30; sample++) {
    if (getpinfo(&ps) == 0) {
      for (int i = 0; i < NPROC; i++) {
        if (ps.inuse[i] && ps.pid[i] == pid) {
          int cur_pri = ps.priority[i];
          if (cur_pri == 0) q0_seen = 1;
          if (cur_pri == 1) q1_seen = 1;
          if (cur_pri == 2) q2_seen = 1;
          if (cur_pri == 3) q3_seen = 1;

          if (cur_pri != last_pri) {
            printf("  Child PID %d transitioned to Q%d | Ticks: [Q0:%d, Q1:%d, Q2:%d, Q3:%d]\n",
                   pid, cur_pri,
                   ps.ticks[i][0], ps.ticks[i][1], ps.ticks[i][2], ps.ticks[i][3]);
            last_pri = cur_pri;
          }
          break;
        }
      }
    }
    if (q3_seen && sample >= 15)
      break;
    pause(1); // Sleep 1 tick to let child burn CPU
  }

  // Terminate child
  kill(pid);
  wait(0);

  printf("Verification Summary:\n");
  printf("  Observed in Q0: %s\n", q0_seen ? "YES" : "NO");
  printf("  Observed in Q1: %s\n", q1_seen ? "YES" : "NO");
  printf("  Observed in Q2: %s\n", q2_seen ? "YES" : "NO");
  printf("  Observed in Q3: %s\n", q3_seen ? "YES" : "NO");

  if (q1_seen && q2_seen && q3_seen) {
    printf("PASS: Process successfully demoted through Q0 -> Q1 -> Q2 -> Q3 and remained in Q3!\n");
    exit(0);
  } else {
    printf("FAIL: Process did not traverse all priority queues properly\n");
    exit(1);
  }
}
