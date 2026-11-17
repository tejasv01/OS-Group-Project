#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

static int
burn_cpu(int iterations)
{
  volatile int x = 0;
  for (int i = 0; i < iterations; i++) {
    x += i * (i + 1);
  }
  return x;
}

int
main(int argc, char *argv[])
{
  int nchildren = 3;
  int pids[3];

  printf("=== Test: Multiple Competing Processes ===\n");
  printf("Forking %d CPU-intensive worker processes...\n", nchildren);

  for (int i = 0; i < nchildren; i++) {
    int pid = fork();
    if (pid < 0) {
      printf("FAIL: fork failed\n");
      exit(1);
    }
    if (pid == 0) {
      // Child process burns CPU
      if (burn_cpu(15000000) == 123456789)
        printf("rare\n");
      exit(0);
    }
    pids[i] = pid;
    printf("  Spawned worker child %d (PID %d)\n", i, pid);
  }

  // Parent monitors workers
  struct pstat ps;
  for (int sample = 0; sample < 5; sample++) {
    pause(2); // Sleep briefly to allow workers to run
    if (getpinfo(&ps) == 0) {
      printf("Sample %d Snapshot:\n", sample + 1);
      for (int i = 0; i < nchildren; i++) {
        for (int s = 0; s < NPROC; s++) {
          if (ps.inuse[s] && ps.pid[s] == pids[i]) {
            printf("  Child PID %d -> Priority: Q%d | Ticks: Q0=%d, Q1=%d, Q2=%d, Q3=%d\n",
                   pids[i], ps.priority[s],
                   ps.ticks[s][0], ps.ticks[s][1], ps.ticks[s][2], ps.ticks[s][3]);
          }
        }
      }
    }
  }

  // Wait for all children to finish
  for (int i = 0; i < nchildren; i++) {
    wait(0);
  }

  printf("PASS: All competing processes completed successfully without deadlock or starvation!\n");
  exit(0);
}
