#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

int
main(int argc, char *argv[])
{
  struct pstat ps;
  printf("=== Test 3: Initial Priority Verification ===\n");

  int pid = fork();
  if (pid < 0) {
    printf("FAIL: fork failed\n");
    exit(1);
  }

  if (pid == 0) {
    // Child immediately checks its own priority
    if (getpinfo(&ps) < 0) {
      printf("FAIL: getpinfo failed in child\n");
      exit(1);
    }
    int my_pid = getpid();
    for (int i = 0; i < NPROC; i++) {
      if (ps.inuse[i] && ps.pid[i] == my_pid) {
        printf("Child (PID %d): Initial Priority = Q%d, Ticks = [Q0:%d, Q1:%d, Q2:%d, Q3:%d]\n",
               my_pid, ps.priority[i],
               ps.ticks[i][0], ps.ticks[i][1], ps.ticks[i][2], ps.ticks[i][3]);
        if (ps.priority[i] == 0) {
          printf("PASS: Newly created process correctly assigned to Q0!\n");
          exit(0);
        } else {
          printf("FAIL: Newly created process priority is Q%d (expected Q0)\n", ps.priority[i]);
          exit(1);
        }
      }
    }
    exit(1);
  } else {
    // Parent waits for child
    int status;
    wait(&status);
    if (status == 0) {
      printf("PASS: Test 3 (Initial Priority) succeeded!\n");
      exit(0);
    } else {
      printf("FAIL: Test 3 failed\n");
      exit(1);
    }
  }
}
