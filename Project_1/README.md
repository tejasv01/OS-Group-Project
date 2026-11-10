# xv6 FUSE Filesystem

A FUSE filesystem that mounts an xv6-riscv `fs.img` on Linux, so the image can be browsed and modified like a normal folder. Includes an fsck-style consistency checker.

## Team

| Member | Responsibility |
|--------|----------------|
|  Tejasv  | TODO |
| Shaurya  | TODO |
| Kushagra | TODO |
|  Bharat  | TODO |
|   Rohit  | TODO |
|  Sarthak | TODO |

## Supported operations

`getattr`, `readdir`, `read`, `write`, `create`, `mkdir`, `unlink`, `truncate`

## Setup (Ubuntu)

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


## Usage

Mount:

```bash
mkdir -p /tmp/mnt
python3 xv6fuse.py fs.img /tmp/mnt -f
```

Unmount:

```bash
fusermount3 -u /tmp/mnt
```

Run the checker:

```bash
python3 fsck.py fs.img
```

Replace the file names above with your actual ones.

**Always unmount before booting xv6 on the same `fs.img`.** Running both at once corrupts the image. Keep a backup copy of a clean `fs.img`.

## Testing

**Linux to xv6:** mount, copy files in, unmount, run `make qemu`, then `cat` the files in xv6.

**xv6 to Linux:** create files in xv6, exit QEMU (Ctrl-a, then x), mount the image, read the files.

Run the checker after every test.

## Repository layout

```
TODO
```

## Known limitations

- TODO

## References

- xv6-riscv: https://github.com/mit-pdos/xv6-riscv (`kernel/fs.h`, `kernel/fs.c`, `mkfs/mkfs.c`)
- xv6 book, file system chapter
- libfuse / fusepy documentation