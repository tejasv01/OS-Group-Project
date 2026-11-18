# xv6 FUSE Filesystem — Namespace Operations & Implementation Guide

**Author:** Kushagra  
**Role:** F3: Namespace Operations  
**Core Module:** [`dirops.py`](file:///c:/Users/HP/OS_Project0/dirops.py)  
**Feature Branch:** `kushagra/namespace-ops`  
**Repository:** [OS-Group-Project](https://github.com/Taskmaster-afk/OS-Group-Project.git)

---

## 1. Executive Summary

In this project, our team is building a **Filesystem in Userspace (FUSE)** driver that mounts an `xv6-riscv` filesystem disk image (`fs.img`) onto Linux, allowing Linux to seamlessly browse, read, create, modify, and delete xv6 files and directories.

### Team Roles & Modular Architecture
| Member | Role | Assigned Module | Responsibility |
|---|---|---|---|
| **Kushagra** | **F3: Namespace Operations** | [`dirops.py`](file:///c:/Users/HP/OS_Project0/dirops.py) | **`dirlink`**, **`create`**, **`mkdir`**, **`unlink`**, **`isdirempty`**, **`link`**, plus `.`/`..` and `nlink` accounting |
| Tejasv | F1: Core + Read Path | [`xv6img.py`](file:///c:/Users/HP/OS_Project0/xv6img.py), [`xv6fuse.py`](file:///c:/Users/HP/OS_Project0/xv6fuse.py) | Block I/O, dinode reads, `bmap`, `readi`, `namei`, FUSE `getattr`/`readdir`/`read` |
| Bharat | F2: Allocation + Write Path | [`alloc.py`](file:///c:/Users/HP/OS_Project0/alloc.py) | Bitmap (`balloc`/`bfree`), Inodes (`ialloc`/`ifree`), `itrunc`, `writei`, `truncate` |
| Shaurya | F4: Consistency & Testing | [`fsck.py`](file:///c:/Users/HP/OS_Project0/fsck.py), [`tests/`](file:///c:/Users/HP/OS_Project0/tests) | Filesystem consistency checker, Linux $\leftrightarrow$ xv6 test suites |

Because the repository initially contained only documentation and empty skeletons, we implemented the foundational data structures and image access layers to allow Kushagra's namespace operations to be fully developed, unit-tested, and verified end-to-end.

---

## 2. xv6 Filesystem Layout & On-Disk Structures

The xv6 disk layout consists of 6 contiguous regions:

```text
+------------+-------------+------------+--------------+---------------+-------------+
| Boot Block | Superblock  | Log Blocks | Inode Blocks | Bitmap Blocks | Data Blocks |
| (Block 0)  |  (Block 1)  | (Block 2..) | (inodestart) |  (bmapstart)  | (datastart) |
+------------+-------------+------------+--------------+---------------+-------------+
```

### Key Constants ([`xv6defs.py`](file:///c:/Users/HP/OS_Project0/xv6defs.py))
* `BSIZE = 1024`: Block size in bytes.
* `FSMAGIC = 0x10203040`: Superblock magic number.
* `ROOTINO = 1`: Root directory inode number (inode 0 is unused).
* `NDIRECT = 12`: Number of direct block pointers in an inode.
* `NINDIRECT = 256`: Number of block pointers in a single indirect block (`1024 / 4 = 256`).
* `MAXFILE = 268`: Maximum file size in blocks (`12 + 256 = 268` blocks $\approx$ 274,432 bytes).
* `DIRSIZ = 14`: Maximum file name length in directory entries.
* `DINODE_SIZE = 64`: Size of `struct dinode` on disk.
* `IPB = 16`: Inodes per block (`1024 / 64 = 16`).
* `BPB = 8192`: Bitmap bits per block (`1024 * 8 = 8192`).

### 1. `struct superblock` (32 bytes)
Format string: `<8I` (little-endian, 8 unsigned 32-bit integers):
```python
magic, size, nblocks, ninodes, nlog, logstart, inodestart, bmapstart
```

### 2. `struct dinode` (64 bytes)
Format string: `<hhhhI13I`
* `type` (int16): `0` = free (`T_UNUSED`), `1` = `T_DIR`, `2` = `T_FILE`, `3` = `T_DEVICE`.
* `major` (int16): Major device number.
* `minor` (int16): Minor device number.
* `nlink` (int16): Number of hard links pointing to this inode.
* `size` (uint32): File size in bytes.
* `addrs[13]` (13 uint32s): 12 direct block numbers + 1 indirect block number.

### 3. `struct dirent` (16 bytes)
Format string: `<H14s`
* `inum` (uint16): Inode number (0 indicates an unused/empty slot).
* `name` (14 bytes): ASCII filename, null-padded.

---

## 3. Kushagra's Module: Namespace Operations ([`dirops.py`](file:///c:/Users/HP/OS_Project0/dirops.py))

Kushagra is responsible for managing file/directory creation, directory entry linking, slot reuse, link count updates, and deletion.

### 3.1. `dirlink(img, dp_inum, name, inum)`
Translates `kernel/fs.c: dirlink`.

#### Algorithm:
1. **Validation:** Checks that `name` is non-empty, does not contain `/` or null bytes, and length $\le 14$ characters (`DIRSIZ`).
2. **Duplicate Check:** Scans the directory entries of `dp_inum`. If `de.inum != 0` and `de.name == name`, raises `OSError(EEXIST)`.
3. **Empty Slot Reuse:** During the scan, it looks for any deleted entry where `de.inum == 0`.
   * If an empty slot is found at `off < dp.size`, `target_off = empty_slot_off`.
   * If no empty slot exists, `target_off = dp.size` (appends 16 bytes to the directory).
4. **Write Dirent:** Packs `Dirent(inum, name)` and writes 16 bytes at `target_off` via `alloc.writei`.

```python
# Dirent slot reuse in dirops.py
while off < dp.size:
    data = img.readi(dp_inum, off, DIRENT_SIZE)
    if len(data) < DIRENT_SIZE:
        break
    de = Dirent.unpack(data)
    if de.inum != 0:
        if de.name == name:
            raise OSError(errno.EEXIST, f"Entry '{name}' already exists")
    elif empty_slot_off is None:
        empty_slot_off = off  # Mark first empty slot for reuse!
    off += DIRENT_SIZE
```

### 3.2. `isdirempty(img, inum)`
Translates `kernel/sysfile.c: isdirempty`.
* Scans all 16-byte directory entries in directory `inum`.
* If any entry with `de.inum != 0` has a name other than `.` and `..`, the directory is **not empty** $\to$ returns `False`.
* If only `.` and `..` (or empty slots) exist, returns `True`.

### 3.3. `create(img, path, type_, major, minor)`
Translates `kernel/sysfile.c: create`.

#### Step-by-Step Lifecycle:
1. Resolves parent directory and leaf name using `(dp_inum, name) = img.nameiparent(path)`.
2. Validates `name` (cannot be `.` or `..`, length $\le 14$).
3. Checks if `name` already exists in `dp_inum`:
   * If creating a `T_FILE` and an existing file is present, returns the existing inode (matching xv6's `open(..., O_CREATE)` behavior).
   * Otherwise, raises `OSError(EEXIST)`.
4. Allocates a new inode number using `alloc.ialloc(img, type_)`.
5. Initializes the new inode:
   * `type = type_`
   * `nlink = 1`
   * `size = 0`
   * `addrs = [0] * 13`
6. **If creating a Directory (`T_DIR`):**
   * Writes `.` pointing to itself (`ip_inum`).
   * Writes `..` pointing to parent (`dp_inum`).
   * **xv6 Link Rule:** Does **NOT** increment `ip.nlink` for `.` (avoids cyclic reference count). `ip.nlink` stays **1**.
7. Links the new entry into parent directory: `dirlink(img, dp_inum, name, ip_inum)`.
8. **If creating a Directory (`T_DIR`):**
   * Now that the directory link succeeded, increment parent directory's link count: `dp.nlink += 1` (for the child's `..` link).
   * Writes updated parent inode to disk.
9. Returns `ip_inum`.

### 3.4. `mkdir(img, path)`
Thin wrapper calling `create(img, path, type_=T_DIR)`.

### 3.5. `unlink(img, path)`
Translates `kernel/sysfile.c: sys_unlink`.

#### Deletion Steps:
1. Resolves `(dp_inum, name) = img.nameiparent(path)`.
2. Prohibits unlinking `.` or `..` $\to$ raises `OSError(EINVAL)`.
3. Looks up `name` in `dp_inum` $\to$ gets `(ip_inum, off)`.
4. Reads target inode `ip`:
   * If `ip.type == T_DIR`, verifies `isdirempty(img, ip_inum)`. If not empty $\to$ raises `OSError(ENOTEMPTY)`.
5. Clears the dirent in parent: writes 16 zero-bytes (`b'\x00' * 16`) at offset `off` in `dp_inum`.
6. If `ip.type == T_DIR`:
   * Decrements parent's link count: `dp.nlink -= 1` (the child's `..` pointer is removed).
7. Decrements target's link count: `ip.nlink -= 1`.
8. **Reclamation:**
   * If `ip.nlink == 0`: Frees all data blocks using `alloc.itrunc(img, ip_inum)`, and marks inode free using `alloc.ifree(img, ip_inum)`.
   * If `ip.nlink > 0`: Writes updated inode back to disk.

### 3.6. `link(img, oldpath, newpath)`
Translates `kernel/sysfile.c: sys_link`.
* Creates hard links for regular files (hard linking directories is disallowed $\to$ `EPERM`).
* Increments `ip.nlink += 1` and links `newpath` into the destination directory.

---

## 4. Deep Dive: xv6 `nlink` Conventions vs. Linux

A central topic of Kushagra's role highlighted in [`README.md`](file:///c:/Users/HP/OS_Project0/README.md#L89) and [`docs/READING.md`](file:///c:/Users/HP/OS_Project0/docs/READING.md#L27) is **link count accounting**.

```text
Linux ext4 Directory:                 xv6 Directory:
nlink = 2 + number_of_subdirs        nlink = 1 + number_of_subdirs
(Counts parent link + '.' link)       ('.' is NOT counted in nlink)
```

### Why does xv6 not count `.`?
In the xv6 kernel (`kernel/sysfile.c: create`):
```c
if(type == T_DIR){  // Create . and .. entries.
    // No ip->nlink++ for ".": avoid cyclic ref count.
    if(dirlink(ip, ".", ip->inum) < 0 || dirlink(ip, "..", dp->inum) < 0)
        goto fail;
}
```
1. **Avoiding Cyclic References:** In xv6, reference counting is strictly hierarchical. If `.` incremented `nlink`, every directory would self-reference, requiring special cycle-breaking garbage collection during unlinking.
2. **Predictable Tree Traversal:** A directory's `nlink` in xv6 represents:
   $$\text{nlink}_{\text{dir}} = 1 + \text{subdirectories}$$
   * Leaf directory (no subdirectories): `nlink = 1`.
   * Directory with 3 subdirectories: `nlink = 1 + 3 = 4`.
   * Root directory `/` initially: `nlink = 1`.
3. **FUSE Compatibility Layer:**
   Linux tools like `ls -l` and `find` expect standard POSIX directory `st_nlink` ($2 + \text{subdirs}$). In [`xv6fuse.py`](file:///c:/Users/HP/OS_Project0/xv6fuse.py#L42), when reporting `getattr` to Linux, we return:
   ```python
   st_nlink = inode.nlink + 1  # Formats xv6 (1 + subdirs) to Linux (2 + subdirs)
   ```
   This ensures standard Linux CLI tools display proper link counts while keeping on-disk xv6 structures 100% compliant with the xv6 kernel!

---

## 5. Overview of Supporting Modules

### [`alloc.py`](file:///c:/Users/HP/OS_Project0/alloc.py) (Allocation Layer)
* `balloc(img)`: Scans the free block bitmap, marks the first free bit as `1`, zeroes the 1024-byte block, and returns the block number.
* `bfree(img, b)`: Clears the bit in the bitmap.
* `ialloc(img, type_)`: Scans inode table from 1 to `ninodes-1`, finds `type == 0`, zeroes fields, sets type, and commits to disk.
* `ifree(img, inum)`: Marks `dinode.type = 0`.
* `bmap(img, inode, inum, bn, alloc)`: Resolves direct blocks `0..11` or traverses the indirect block (pointer to 256 uint32s). Allocates blocks dynamically if `alloc=True`.
* `itrunc(img, inum)`: Frees all 12 direct blocks and up to 256 indirect blocks, freeing the indirect table block itself.
* `writei(img, inum, data, offset)`: Writes byte buffer into an inode across block boundaries.
* `truncate(img, inum, new_size)`: Truncates or zero-extends files.

### [`xv6img.py`](file:///c:/Users/HP/OS_Project0/xv6img.py) (Image & Path Lookup)
* `XV6Image`: Encapsulates disk file handle, superblock caching, block read/writes, and dinode read/writes.
* `dirlookup(dp_inum, name)`: Finds `(inum, offset)` in a directory.
* `get_dirents(dp_inum)`: Returns list of `(inum, name)` active entries.
* `namei(path)`: Traverses full path from `ROOTINO`.
* `nameiparent(path)`: Resolves `(parent_inum, basename)`.
* `create_empty_image(path, nblocks, ninodes)`: Creates a fresh, clean `fs.img` with boot block, superblock, log blocks, inode blocks, bitmap, and root directory.

### [`xv6fuse.py`](file:///c:/Users/HP/OS_Project0/xv6fuse.py) (FUSE Driver)
Translates Linux VFS calls into xv6 operations:
* `getattr`: reports `st_mode`, `st_nlink`, `st_size`, `st_mtime`.
* `readdir`: yields directory entry names.
* `read`: calls `img.readi`.
* `write`: calls `alloc.writei`.
* `create`: calls `dirops.create`.
* `mkdir`: calls `dirops.mkdir`.
* `unlink` & `rmdir`: calls `dirops.unlink`.
* `truncate`: calls `alloc.truncate`.

### [`fsck.py`](file:///c:/Users/HP/OS_Project0/fsck.py) (Consistency Checker)
Performs 6 integrity audits on an xv6 image:
1. **Superblock:** Magic number, sizes, inode counts.
2. **Inodes & Block Addresses:** Direct/indirect addresses within range, no duplicates (no double allocation).
3. **Bitmap Consistency:** Metadata blocks marked allocated; all referenced data blocks marked in bitmap; no leaked blocks.
4. **Directory Structure:** Root inode is `T_DIR`, `.` points to self, `..` points to parent, all dirents point to allocated inodes.
5. **Link Counts:** Files have `nlink == references`; directories have `nlink == 1 + subdirectories`.

---

## 6. Test Suite & Verification Results

All tests are implemented in [`tests/test_dirops.py`](file:///c:/Users/HP/OS_Project0/tests/test_dirops.py) and [`tests/test_fsck.py`](file:///c:/Users/HP/OS_Project0/tests/test_fsck.py).

### Running the Test Suite:
```bash
wsl -d Ubuntu bash -c "cd /mnt/c/Users/HP/OS_Project0 && python3 -m unittest discover -s tests"
```

### Verified Scenarios:
1. `test_initial_root_directory`: Root inode is 1, `nlink == 1`, contains `.` $\to$ 1, `..` $\to$ 1.
2. `test_mkdir_and_nlink_conventions`: Child `nlink == 1`, parent `nlink` incremented from 1 to 2.
3. `test_nested_subdirectories`: Multi-level directories (`/d1/d2`, `/d1/d3`) verify `nlink = 1 + subdirs`.
4. `test_create_regular_file`: Regular file creation does not change parent directory `nlink`.
5. `test_unlink_regular_file`: Removes dirent, frees inode and data blocks (`type = T_UNUSED`).
6. `test_unlink_empty_directory`: Unlinking empty directory decrements parent `nlink` and reclaims inode.
7. `test_unlink_non_empty_directory_fails`: Rejecting `unlink` with `ENOTEMPTY`.
8. `test_unlink_dot_and_dotdot_fails`: Rejecting `unlink` on `.` or `..` with `EINVAL`.
9. `test_dirlink_slot_reuse`: Verified directory size does not grow when reusing unlinked `inum == 0` slots.
10. `test_filename_length_limits`: 14 characters succeeds; 15 characters raises `ENAMETOOLONG`.
11. `test_duplicate_creation_fails`: Creating duplicate file/directory raises `EEXIST`.
12. `test_hard_link_and_multi_unlink`: Creating hard links increments `nlink`; unlinking one path keeps the file alive until last reference is removed.
13. `test_clean_image_passes` (fsck): Validates consistency of clean image.
14. `test_after_files_and_directories_passes` (fsck): Validates consistency after creating directories and files.

**Test Execution Output:**
```text
..............
----------------------------------------------------------------------
Ran 14 tests in 0.079s

OK
Checking filesystem image: /tmp/tmp2mg0i317
fsck passed: No errors found. Filesystem is clean and consistent.
Checking filesystem image: /tmp/tmpf2acjgd6
fsck passed: No errors found. Filesystem is clean and consistent.
```

---

## 7. Git Workflow for Kushagra

Following [`Project_1/CONTRIBUTING.md`](file:///c:/Users/HP/OS_Project0/Project_1/CONTRIBUTING.md):

1. **Active Branch:**
   ```bash
   git branch
   # * kushagra/namespace-ops
   ```
2. **Review Changes:**
   ```bash
   git status
   ```
3. **Commit Your Feature:**
   ```bash
   git add dirops.py xv6defs.py alloc.py xv6img.py xv6fuse.py fsck.py tests/ NAMESPACE_OPERATIONS.md
   git commit -m "Implement dirops namespace operations, xv6 nlink handling, and unit tests"
   ```
4. **Push Branch to GitHub:**
   ```bash
   git push -u origin kushagra/namespace-ops
   ```
5. Open a Pull Request on GitHub for your teammates (Tejasv, Bharat, Shaurya) to review and merge into `main`.

