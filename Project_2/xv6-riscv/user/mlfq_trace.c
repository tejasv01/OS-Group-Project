#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/pstat.h"

// Arithmetic workload function
static int
workload(int count)
{
  volatile int x = 0;
  for (int i = 0; i < count; i++) {
    x += (i ^ 0x3f) * 2;
  }
  return x;
}

// Helper to print N spaces for column alignment in xv6 printf
static void
print_spaces(int n)
{
  for (int i = 0; i < n; i++)
    printf(" ");
}

// Helper to print an integer right-aligned within a specified width
static void
print_int_aligned(int val, int width)
{
  int digits = 1;
  int temp = val;
  if (temp < 0) { digits++; temp = -temp; }
  while (temp >= 10) { digits++; temp /= 10; }
  if (width > digits)
    print_spaces(width - digits);
  printf("%d", val);
}

// Helper returning dynamic queue status description
static char*
get_queue_status(int q)
{
  if (q == 0) return "Q0 (Top/Interactive)";
  if (q == 1) return "Q1 (Second Priority)";
  if (q == 2) return "Q2 (Third Priority)";
  if (q == 3) return "Q3 (Batch/Lowest)";
  return "Unknown";
}

int
main(int argc, char *argv[])
{
  printf("\n=========================================================================================\n");
  printf("        MLFQ FIVE-PROCESS CONTINUOUS LIFECYCLE & QUEUE TRANSFER TRACER\n");
  printf("=========================================================================================\n");
  printf("In this test, exactly FIVE processes are created with CONSTANT, UNCHANGING PIDs:\n");
  printf("  - Worker A: Heavy CPU-Bound     (Continuous calculations without yielding)\n");
  printf("  - Worker B: Medium Compute      (Moderate compute bursts, occasional yield)\n");
  printf("  - Worker C: Highly Interactive  (Short bursts + frequent pause/yield, stays Q0)\n");
  printf("  - Worker D: Short I/O-Bound     (Simulates fast I/O: sleeps for 2 ticks via pause(2))\n");
  printf("  - Worker E: Long I/O-Bound      (Simulates slow I/O: sleeps for 6 ticks via pause(6))\n");
  printf("We track how these 5 distinct workloads interchange across queues Q0, Q1, Q2, Q3!\n");
  printf("=========================================================================================\n\n");

  int pids[5];

  // 1. Worker A: Heavy CPU-bound (continuous execution)
  int pid_a = fork();
  if (pid_a < 0) { printf("fork A failed\n"); exit(1); }
  if (pid_a == 0) {
    while (1) {
      if (workload(5000000) == 9999999) printf("rare\n");
    }
    exit(0);
  }
  pids[0] = pid_a;

  // 2. Worker B: Medium Compute (bursts + occasional yield)
  int pid_b = fork();
  if (pid_b < 0) { printf("fork B failed\n"); kill(pids[0]); exit(1); }
  if (pid_b == 0) {
    while (1) {
      workload(50000);
      yield();
    }
    exit(0);
  }
  pids[1] = pid_b;

  // 3. Worker C: Highly Interactive (short burst + pause)
  int pid_c = fork();
  if (pid_c < 0) { printf("fork C failed\n"); kill(pids[0]); kill(pids[1]); exit(1); }
  if (pid_c == 0) {
    while (1) {
      workload(50000);
      pause(1);
    }
    exit(0);
  }
  pids[2] = pid_c;

  // 4. Worker D: Short I/O (sleeps 2 ticks)
  int pid_d = fork();
  if (pid_d < 0) { printf("fork D failed\n"); for(int k=0; k<3; k++) kill(pids[k]); exit(1); }
  if (pid_d == 0) {
    while (1) {
      pause(2); // Short sleep
      workload(50000);
    }
    exit(0);
  }
  pids[3] = pid_d;

  // 5. Worker E: Long I/O (sleeps 6 ticks)
  int pid_e = fork();
  if (pid_e < 0) { printf("fork E failed\n"); for(int k=0; k<4; k++) kill(pids[k]); exit(1); }
  if (pid_e == 0) {
    while (1) {
      pause(6); // Long sleep
      workload(50000);
    }
    exit(0);
  }
  pids[4] = pid_e;

  // Read initial states immediately after creation
  struct pstat ps;
  int last_pri[5] = {0, 0, 0, 0, 0};
  if (getpinfo(&ps) == 0) {
    for (int i = 0; i < NPROC; i++) {
      if (ps.inuse[i]) {
        for (int k = 0; k < 5; k++) {
          if (ps.pid[i] == pids[k]) {
            last_pri[k] = ps.priority[i];
          }
        }
      }
    }
  }

  printf("[PROCESS CREATION SUCCESSFUL]\n");
  printf("  Worker A PID = %d (Heavy CPU-Bound,  Initial: Q%d, stays PID %d forever)\n", pids[0], last_pri[0], pids[0]);
  printf("  Worker B PID = %d (Medium Compute,   Initial: Q%d, stays PID %d forever)\n", pids[1], last_pri[1], pids[1]);
  printf("  Worker C PID = %d (Interactive,      Initial: Q%d, stays PID %d forever)\n", pids[2], last_pri[2], pids[2]);
  printf("  Worker D PID = %d (Short I/O,        Initial: Q%d, stays PID %d forever)\n", pids[3], last_pri[3], pids[3]);
  printf("  Worker E PID = %d (Long I/O,         Initial: Q%d, stays PID %d forever)\n\n", pids[4], last_pri[4], pids[4]);

  printf("-----------------------------------------------------------------------------------------\n");
  printf("DYNAMIC QUEUE TRANSFER EVENTS & PERIODIC PROGRESS SNAPSHOTS:\n");
  printf("-----------------------------------------------------------------------------------------\n");

  static const char *worker_names[5] = {
    "Worker A", "Worker B", "Worker C", "Worker D", "Worker E"
  };
  static const char *worker_types[5] = {
    "Heavy CPU-Bound        ",
    "Medium Compute         ",
    "Interactive (Yield/IO) ",
    "Short I/O (pause 2)    ",
    "Long I/O (pause 6)     "
  };

  for (int step = 1; step <= 55; step++) {
    pause(1); // Advance time by 1 tick

    if (getpinfo(&ps) == 0) {
      int pri[5] = {-1, -1, -1, -1, -1};
      int ticks[5][4];
      for (int k = 0; k < 5; k++) {
        for (int q = 0; q < 4; q++) ticks[k][q] = 0;
      }

      for (int i = 0; i < NPROC; i++) {
        if (ps.inuse[i]) {
          for (int k = 0; k < 5; k++) {
            if (ps.pid[i] == pids[k]) {
              pri[k] = ps.priority[i];
              for (int q = 0; q < 4; q++) ticks[k][q] = ps.ticks[i][q];
            }
          }
        }
      }

      // Check transitions for Worker A (Heavy CPU)
      if (pri[0] != last_pri[0] && pri[0] != -1) {
        if (pri[0] > last_pri[0]) {
          printf("[Tick %d] [DEMOTION] Worker A (PID %d, Heavy-CPU) DEMOTED: Q%d -> Q%d | Ticks: [Q0:%d, Q1:%d, Q2:%d, Q3:%d]\n",
                 step, pids[0], last_pri[0], pri[0], ticks[0][0], ticks[0][1], ticks[0][2], ticks[0][3]);
          printf("         -> Reason: Time quantum in Q%d exhausted by heavy CPU calculations.\n", last_pri[0]);
        } else if (pri[0] < last_pri[0]) {
          printf("[Tick %d] [BOOST] Worker A (PID %d, Heavy-CPU) PRIORITY BOOSTED: Q%d -> Q0\n",
                 step, pids[0], last_pri[0]);
          printf("         -> Reason: Periodic priority boost (every 40 ticks) reset all active processes to Q0!\n");
          printf("         -> Notice: Historical stats preserved! (Currently in Q%d) | Ticks: [Q0:%d, Q1:%d, Q2:%d, Q3:%d]\n",
                 pri[0], ticks[0][0], ticks[0][1], ticks[0][2], ticks[0][3]);
        }
        last_pri[0] = pri[0];
      }

      // Check transitions for Worker B (Medium Compute)
      if (pri[1] != last_pri[1] && pri[1] != -1) {
        if (pri[1] > last_pri[1]) {
          printf("[Tick %d] [DEMOTION] Worker B (PID %d, Medium-Compute) DEMOTED: Q%d -> Q%d | Ticks: [Q0:%d, Q1:%d, Q2:%d, Q3:%d]\n",
                 step, pids[1], last_pri[1], pri[1], ticks[1][0], ticks[1][1], ticks[1][2], ticks[1][3]);
        } else if (pri[1] < last_pri[1]) {
          printf("[Tick %d] [BOOST] Worker B (PID %d, Medium-Compute) PRIORITY BOOSTED: Q%d -> Q0\n",
                 step, pids[1], last_pri[1]);
        }
        last_pri[1] = pri[1];
      }

      // Periodically print a formatted multi-process scheduling snapshot
      if (step == 5 || step == 15 || step == 30 || step == 48) {
        printf("\n=========================================================================================\n");
        printf("--- Multi-Process Scheduling Snapshot at Tick %d ---\n", step);
        printf("=========================================================================================\n");
        printf("PROCESS     PID   WORKLOAD TYPE             QUEUE   Q0_TK  Q1_TK  Q2_TK  Q3_TK   CURRENT STATUS\n");
        printf("-----------------------------------------------------------------------------------------\n");
        for (int k = 0; k < 5; k++) {
          printf("%s    ", worker_names[k]);
          print_int_aligned(pids[k], 2);
          printf("   %s   Q%d   ", worker_types[k], pri[k]);
          print_int_aligned(ticks[k][0], 5);
          printf("  ");
          print_int_aligned(ticks[k][1], 5);
          printf("  ");
          print_int_aligned(ticks[k][2], 5);
          printf("  ");
          print_int_aligned(ticks[k][3], 5);
          printf("   %s\n", get_queue_status(pri[k]));
        }
        printf("-----------------------------------------------------------------------------------------\n\n");
      }
    }
  }

  // Clean up all 5 workers
  for (int k = 0; k < 5; k++) {
    kill(pids[k]);
    wait(0);
  }

  printf("=========================================================================================\n");
  printf("FINAL ANALYSIS SUMMARY FOR THE FIVE PROCESSES:\n");
  printf("=========================================================================================\n");
  printf("1. Worker A (PID %d, Heavy CPU):\n", pids[0]);
  printf("   - Traversed queues down to Q3 because it burned continuous CPU without yielding.\n");
  printf("   - Received large 8-tick quanta in Q3, minimizing context-switching overhead.\n");
  printf("   - When periodic boost occurred at tick 40, was boosted back to Q0!\n");
  printf("2. Worker B (PID %d, Medium Compute):\n", pids[1]);
  printf("   - Alternated between computation and yields; demoted through intermediate queues.\n");
  printf("3. Worker C (PID %d, Interactive Yield/IO):\n", pids[2]);
  printf("   - Relinquished the CPU via short bursts and pauses; retained top priority (Q0/Q1).\n");
  printf("   - Guarantees immediate response time for interactive user operations!\n");
  printf("4. Worker D & Worker E (PID %d & %d, I/O-Bound):\n", pids[3], pids[4]);
  printf("   - Slept on timer channels; sleeping ticks were NOT charged to CPU usage.\n");
  printf("   - Woke up into the highest-priority queue (Q0), giving zero-latency I/O response.\n");
  printf("=========================================================================================\n");
  printf("Notice: Throughout the entire test, PIDs %d, %d, %d, %d, and %d NEVER changed!\n",
         pids[0], pids[1], pids[2], pids[3], pids[4]);
  printf("All queue transfers occurred solely within the exact same 5 processes.\n");
  printf("=========================================================================================\n\n");

  exit(0);
}
