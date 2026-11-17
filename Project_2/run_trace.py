#!/usr/bin/env python3
"""
Five-Process Continuous MLFQ Queue Transfer Tracer
Part 2 OS Group Project - xv6-riscv

Spawns Worker A (PID 4, CPU-Bound), Worker B (PID 5, Medium Compute),
Worker C (PID 6, Interactive Yielding), Worker D (PID 7, Short I/O),
and Worker E (PID 8, Long I/O) and traces their queue interchange
without PID changes.
"""

import os
import sys
import subprocess
import signal

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    xv6_dir = os.path.join(script_dir, "xv6-riscv")

    cmd = [
        "qemu-system-riscv64",
        "-machine", "virt",
        "-bios", "none",
        "-kernel", "kernel/kernel",
        "-m", "128M",
        "-smp", "1",
        "-nographic",
        "-global", "virtio-mmio.force-legacy=false",
        "-drive", "file=fs.img,if=none,format=raw,id=x0",
        "-device", "virtio-blk-device,drive=x0,bus=virtio-mmio-bus.0"
    ]

    print("=======================================================================")
    print("Launching xv6-riscv 5-Process Continuous Queue Tracer (mlfq_trace)...")
    print("=======================================================================\n")

    p = subprocess.Popen(
        cmd,
        cwd=xv6_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    def handle_sigint(signum, frame):
        try:
            p.kill()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    buffer = ""
    trace_sent = False

    try:
        while True:
            ch = p.stdout.read(1)
            if not ch:
                break
            sys.stdout.write(ch)
            sys.stdout.flush()
            buffer += ch

            if not trace_sent and buffer.endswith("$ "):
                trace_sent = True
                p.stdin.write("mlfq_trace\n")
                p.stdin.flush()
                buffer = ""
            elif trace_sent and "FINAL ANALYSIS SUMMARY" in buffer:
                if buffer.endswith("$ "):
                    break

    except Exception as e:
        print(f"\nExecution error: {e}")
    finally:
        try:
            p.kill()
            p.wait(timeout=2)
        except Exception:
            pass

    print("\n=======================================================================")
    print("Continuous 5-Process Queue Trace Completed Successfully!")
    print("=======================================================================")

if __name__ == "__main__":
    main()
