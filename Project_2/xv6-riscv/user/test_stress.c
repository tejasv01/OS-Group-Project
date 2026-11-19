#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

int
main(int argc, char *argv[])
{
  printf("=== Test: MLFQ Stress Testing ===\n");
  int nprocs = 6;

  for (int i = 0; i < nprocs; i++) {
    int pid = fork();
    if (pid < 0) {
      printf("FAIL: stress fork failed\n");
      exit(1);
    }
    if (pid == 0) {
      // Child behavior varies based on index
      if (i % 3 == 0) {
        // CPU bound
        volatile int x = 0;
        for (int k = 0; k < 10000000; k++) {
          x += k;
        }
        if (x == 123456789)
          printf("rare\n");
      } else if (i % 3 == 1) {
        // Interactive yielding
        for (int k = 0; k < 100; k++) {
          yield();
        }
      } else {
        // Sleeping and waking
        for (int k = 0; k < 5; k++) {
          pause(2);
        }
      }
      exit(0);
    }
  }

  // Parent monitors and queries getpinfo repeatedly
  struct pstat ps;
  for (int k = 0; k < 10; k++) {
    if (getpinfo(&ps) < 0) {
      printf("FAIL: getpinfo during stress test failed\n");
      exit(1);
    }
    pause(1);
  }

  // Collect all children
  for (int i = 0; i < nprocs; i++) {
    wait(0);
  }

  printf("PASS: MLFQ stress test completed cleanly with no panics or deadlocks!\n");
  exit(0);
}
