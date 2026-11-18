# Namespace Operations Notes (`dirops.py`)

Notes for F3 (`dirops.py`), covering directory entry linking, file/directory creation, unlinking, hard links, and how xv6 handles `nlink`.

## Functions in `dirops.py`

- **`dirlink(img, dp_inum, name, inum)`** (from `kernel/fs.c: dirlink`)
  - Rejects empty names, `/`, NUL bytes, and names longer than `DIRSIZ` (14 bytes).
  - Scans `dp_inum` entries in 16-byte chunks: raises `EEXIST` if `name` is already there, and remembers the first `inum == 0` slot so deleted entries get reused instead of always appending at EOF.

- **`isdirempty(img, inum)`** (from `kernel/sysfile.c: isdirempty`)
  - Checks every active entry (`inum != 0`). Returns `False` if anything other than `.` and `..` exists.

- **`create(img, path, type_, major, minor)`** and **`mkdir(img, path)`** (from `kernel/sysfile.c`)
  - Resolves parent with `nameiparent`. If creating a `T_FILE` that already exists (and is a file/device), returns the existing inode number like xv6 `O_CREATE`.
  - Allocates an inode (`nlink = 1`). For `T_DIR`, creates `.` -> `ip_inum` and `..` -> `dp_inum`, links the new directory into `dp_inum`, then increments `dp.nlink`.
  - Rolls back (`itrunc` + `ifree`) if linking fails.

- **`unlink(img, path)`**
  - Blocks unlinking `.` or `..` (`EINVAL`) and non-empty directories (`ENOTEMPTY`).
  - Zeroes out the 16-byte dirent in the parent directory, decrements `dp.nlink` when removing a subdir, decrements `ip.nlink`, and frees blocks + inode once `ip.nlink == 0`.

- **`link(img, oldpath, newpath)`**
  - Hard links regular files (`EPERM` on directories), bumps `ip.nlink`, and rolls back if `dirlink` fails.

## xv6 `nlink` vs Linux

- On Linux (e.g. ext4), a directory's `nlink` is `2 + subdirs` (parent entry + `.` + each subdir's `..`).
- In xv6 (`kernel/sysfile.c: create`), `.` is **not** counted in `nlink`, so a directory's on-disk `nlink` is `1 + subdirs` (avoiding cyclic ref counts).
- `xv6fuse.py` translates this in `getattr()` by returning `ip.nlink + 1` to the Linux VFS, keeping `ls -l` / `find` happy while keeping `fs.img` valid for `xv6-riscv` and `fsck.py`.

## Running tests

From `Project_1/`:

```bash
python3 -m unittest discover -s tests -v
```
