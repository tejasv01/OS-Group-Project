#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

int
main(int argc, char *argv[])
{
  struct pstat ps;
  int my_pid = getpid();
  int found_self = 0;

  printf("=== Test: getpinfo System Call ===\n");

  // Test 1: Null pointer should safely fail
  if (getpinfo(0) != -1) {
    printf("FAIL: getpinfo(0) did not return -1\n");
    exit(1);
  }
  printf("PASS: getpinfo(0) returned -1 as expected\n");

  // Test 2: Invalid memory pointer should safely fail
  if (getpinfo((struct pstat *)0xffffffff00000000L) != -1) {
    printf("FAIL: getpinfo(invalid_ptr) did not return -1\n");
    exit(1);
  }
  printf("PASS: getpinfo(invalid_ptr) returned -1 as expected\n");

  // Test 3: Valid pointer should succeed
  if (getpinfo(&ps) < 0) {
    printf("FAIL: getpinfo(&ps) failed\n");
    exit(1);
  }
  printf("PASS: getpinfo(&ps) returned 0 (success)\n");

  // Test 4: Verify current process PID exists and fields are sane
  for (int i = 0; i < NPROC; i++) {
    if (ps.inuse[i]) {
      if (ps.pid[i] == my_pid) {
        found_self = 1;
        printf("PASS: found self (PID %d) at slot %d with priority %d\n",
               my_pid, i, ps.priority[i]);
        if (ps.priority[i] < 0 || ps.priority[i] > 3) {
          printf("FAIL: priority out of range (0-3): %d\n", ps.priority[i]);
          exit(1);
        }
      }
    } else {
      // Unused slot must be cleanly zeroed
      if (ps.pid[i] != 0 || ps.priority[i] != 0) {
        printf("FAIL: unused slot %d contains non-zero data\n", i);
        exit(1);
      }
    }
  }

  if (!found_self) {
    printf("FAIL: did not find own PID in process table\n");
    exit(1);
  }

  printf("PASS: all getpinfo() tests passed successfully!\n");
  exit(0);
}
