# Operating Systems Group Project
# xv6 FUSE Filesystem + MLFQ Scheduler

OS group project with two parts:

1. **FUSE filesystem** that mounts an xv6-riscv `fs.img` on Linux, so the image can be browsed and modified like a normal folder. Includes an fsck-style consistency checker.
2. **MLFQ scheduler** for xv6-riscv that favors interactive processes, with a `getpinfo` syscall.

## Team

| Member | Role | Responsibility |
|--------|------|----------------|
| Tejasv | F1: Core + read path | `xv6img.py` (block IO, inodes, `bmap`, `readi`, path lookup) and `xv6fuse.py` (`getattr`, `readdir`, `read`) |
| Bharat | F2: Allocation + write | `alloc.py`: `balloc`/`bfree` (bitmap), `ialloc`/`ifree`, `itrunc`, `writei`, `truncate` |
| Kushagra | F3: Namespace operations | `dirops.py`: `dirlink`, `create`, `mkdir`, `unlink` (including `.`/`..` and nlink handling) |
| Shaurya | F4: fsck + testing | `fsck.py` and the Linux to xv6 / xv6 to Linux test scripts in `tests/` |
| Rohit | M1: Scheduler | `kernel/proc.h`, `kernel/proc.c` (MLFQ `scheduler()`, queue levels, priority boost) |
| Sarthak | M2: Trap + syscall + tests | `kernel/trap.c` (tick accounting, demotion), `getpinfo` syscall, user test programs |

## Part 1: FUSE filesystem

### Supported operations

`getattr`, `readdir`, `read`, `write`, `create`, `mkdir`, `unlink`, `truncate`

### Setup (Ubuntu)

Install xv6 and its tools:

```bash
sudo apt-get update
sudo apt-get install -y git build-essential gdb-multiarch \
    qemu-system-riscv gcc-riscv64-linux-gnu binutils-riscv64-linux-gnu
git clone https://github.com/mit-pdos/xv6-riscv.git
cd xv6-riscv
make fs.img
```

Install FUSE tooling:

```bash
sudo apt-get install -y fuse3 libfuse3-dev pkg-config python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install fusepy
```

> **Note:** classic `fusepy` loads libfuse **2**. If you get "Unable to find fuse library",
> install `libfuse2` (`libfuse2t64` on Ubuntu 24.04+), or use `pip install mfusepy`, a fork
> that supports libfuse3 (then `import mfusepy as fuse`).

### Usage

Mount:

```bash
mkdir -p /tmp/mnt
python3 Project_1/xv6fuse.py fs.img /tmp/mnt -f
```

Unmount:

```bash
fusermount3 -u /tmp/mnt
```

Run the checker:

```bash
python3 Project_1/fsck.py fs.img
```

**Always unmount before booting xv6 on the same `fs.img`.** Running both at once corrupts the image. Keep a backup copy of a clean `fs.img`.

### Testing

**Linux to xv6:** mount, copy files in, unmount, run `make qemu`, then `cat` the files in xv6.

**xv6 to Linux:** create files in xv6, exit QEMU (Ctrl-a, then x), mount the image, read the files.

Run the checker after every test.

### Design notes

- `xv6defs.py` mirrors `kernel/fs.h` (little-endian, no padding): `BSIZE=1024`, 12 direct blocks + 1 indirect (256 entries), 64-byte inodes, 16-byte directory entries, superblock in block 1.
- `XV6Image` works on a plain image file with no FUSE dependency, so every layer can be unit-tested with ordinary Python. `xv6fuse.py` is only a thin wrapper.
- No inode cache: every operation reads inodes fresh and writes them back, which keeps the image consistent at all times.
- xv6's write-ahead log is bypassed. This is safe because the image is never used by FUSE and QEMU simultaneously.
- Directory `nlink` follows xv6's convention: `.` is not counted (a directory's nlink is 1 plus its number of subdirectories).

## Part 2: MLFQ scheduler

Implemented in a separate xv6-riscv clone (`mlfq/` holds the patch and test programs), not in the FUSE code.

- 4 priority queues with time quanta of 1, 2, 4 and 8 ticks.
- A process that uses its whole quantum is demoted one level; one that gives up the CPU early stays at its level.
- Every N ticks all processes are boosted back to the top queue to prevent starvation.
- `getpinfo` syscall returns each process's queue level and ticks spent at each level.
- Files changed: `kernel/proc.c`, `kernel/proc.h`, `kernel/trap.c`, plus the syscall plumbing (`pstat.h`, `syscall.h`, `syscall.c`, `sysproc.c`, `user.h`, `usys.pl`).

Run with `make qemu CPUS=1` for deterministic scheduling when testing.

## Repository layout

```
.
├── Project_1/
│   ├── xv6defs.py               constants and on-disk structs (from kernel/fs.h)
│   ├── xv6img.py                image access: block IO, inodes, bmap, readi, path lookup
│   ├── alloc.py                 bitmap/inode allocation, writei, truncate
│   ├── dirops.py                dirlink, create, mkdir, unlink
│   ├── xv6fuse.py               FUSE wrapper (getattr, readdir, read, write, ...)
│   ├── fsck.py                  consistency checker
│   ├── dirops_notes.md          notes on namespace ops and xv6 nlink rules
│   ├── tests/                   Linux <-> xv6 test scripts and unit tests
│   ├── requirements.txt         pinned Python dependencies
│   └── CONTRIBUTING.md
├── Project_2/                   MLFQ scheduler project
├── docs/                        reading list and project docs
└── README.md
```

## Known limitations

- Maximum file size is 268 blocks (274,432 bytes), the xv6 limit.
- File names are limited to 14 bytes.
- No permissions, ownership or timestamps: xv6 does not store them, so FUSE reports fixed values.
- No rename, symlinks, chmod or device files.
- Single-threaded; not crash-safe because the xv6 log is bypassed.

## References

- xv6-riscv: https://github.com/mit-pdos/xv6-riscv (`kernel/fs.h`, `kernel/fs.c`, `mkfs/mkfs.c`)
- xv6 book, file system chapter and scheduling chapter
- libfuse / fusepy documentation
