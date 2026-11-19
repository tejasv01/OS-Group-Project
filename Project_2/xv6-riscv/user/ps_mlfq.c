#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

int
main(int argc, char *argv[])
{
  struct pstat ps;

  if (getpinfo(&ps) < 0) {
    printf("ps_mlfq: getpinfo failed\n");
    exit(1);
  }

  printf("=== xv6 MLFQ Process Table ===\n");
  printf("SLOT  PID   STATE  PRIORITY   Q0_TICKS  Q1_TICKS  Q2_TICKS  Q3_TICKS  TOTAL\n");
  printf("---------------------------------------------------------------------------\n");

  int count = 0;
  for (int i = 0; i < NPROC; i++) {
    if (ps.inuse[i]) {
      int total = ps.ticks[i][0] + ps.ticks[i][1] + ps.ticks[i][2] + ps.ticks[i][3];
      printf(" %d\t %d\t USED\t Q%d\t\t %d\t  %d\t  %d\t  %d\t  %d\n",
             i,
             ps.pid[i],
             ps.priority[i],
             ps.ticks[i][0],
             ps.ticks[i][1],
             ps.ticks[i][2],
             ps.ticks[i][3],
             total);
      count++;
    }
  }

  printf("---------------------------------------------------------------------------\n");
  printf("Total active processes: %d\n", count);
  exit(0);
}
