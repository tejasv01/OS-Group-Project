# Consistency checker (fsck) for xv6 fs.img disk images.
# Checks superblock layout, inode types & block pointers, duplicate blocks,
# bitmap vs referenced blocks, directory '.'/'..' links, and nlink counts.

import sys
import struct
from collections import defaultdict

from xv6defs import (
    BSIZE, BPB, IPB, FSMAGIC, ROOTINO,
    T_UNUSED, T_DIR, T_FILE, T_DEVICE,
    NDIRECT, NINDIRECT, DIRENT_SIZE, Dirent, BBLOCK
)
from xv6img import XV6Image


class ConsistencyError(Exception):
    pass


class XV6Fsck:
    def __init__(self, img_path):
        self.img_path = img_path
        self.img = None
        self.sb = None
        self.errors = []

    def log_error(self, msg):
        self.errors.append(msg)

    def close(self):
        if self.img is not None:
            self.img.close()
            self.img = None

    # ------------------------------------------------------------------
    # First data block from superblock fields (same formula as create_empty_image)
    # ------------------------------------------------------------------
    def _compute_datastart(self):
        sb = self.sb
        nbmapblocks = (sb.size + BPB - 1) // BPB
        return sb.bmapstart + nbmapblocks

    def run(self):
        try:
            # Check magic manually first so a corrupt image doesn't blow up inside XV6Image()
            try:
                with open(self.img_path, "rb") as raw_f:
                    raw_f.seek(BSIZE)        # block 1
                    raw_magic = struct.unpack_from("<I", raw_f.read(4))[0]
                    if raw_magic != FSMAGIC:
                        self.log_error(
                            f"Invalid magic number: 0x{raw_magic:08x} "
                            f"(expected 0x{FSMAGIC:08x})"
                        )
                        return self._print_results()
            except (IOError, OSError) as exc:
                self.log_error(f"Cannot read filesystem image: {exc}")
                return self._print_results()

            try:
                self.img = XV6Image(self.img_path, mode="rb")
                self.sb  = self.img.sb
            except (ValueError, IOError, OSError) as exc:
                self.log_error(f"Cannot open filesystem image: {exc}")
                return self._print_results()

            print(f"Checking filesystem image: {self.img.filepath}")

            # Phase 1 - superblock. Bail early if broken since later phases depend on it.
            self.check_superblock()
            if self.errors:
                self._print_results()
                return False

            datastart = self._compute_datastart()

            used_blocks       = defaultdict(list)
            inode_ref_counts  = defaultdict(int)
            dir_subdir_counts = defaultdict(int)
            visited_dirs      = set()

            # Run the rest together so we surface as many errors as possible in one go
            self.check_inodes_and_blocks(datastart, used_blocks)
            self.check_directories(ROOTINO, ROOTINO, visited_dirs,
                                   inode_ref_counts, dir_subdir_counts)
            self.check_link_counts(inode_ref_counts, dir_subdir_counts)
            self.check_bitmap(datastart, set(used_blocks.keys()))

            return self._print_results()

        finally:
            self.close()

    # ------------------------------------------------------------------
    # Phase 1: Superblock
    # ------------------------------------------------------------------
    def check_superblock(self):
        sb = self.sb

        if sb.size <= 0:
            self.log_error(f"Filesystem size is invalid: {sb.size}")

        if sb.ninodes <= 0:
            self.log_error(f"Inode count is invalid: {sb.ninodes}")

        if sb.nlog <= 0:
            self.log_error(f"Log size is invalid: {sb.nlog}")

        # Expected disk layout order: logstart < inodestart < bmapstart < size
        if sb.logstart < 2:
            self.log_error(
                f"logstart ({sb.logstart}) must be >= 2 "
                f"(blocks 0 and 1 are reserved for boot and superblock)"
            )

        if sb.inodestart <= sb.logstart:
            self.log_error(
                f"inodestart ({sb.inodestart}) must be > "
                f"logstart ({sb.logstart})"
            )

        if sb.bmapstart <= sb.inodestart:
            self.log_error(
                f"bmapstart ({sb.bmapstart}) must be > "
                f"inodestart ({sb.inodestart})"
            )

        if sb.size > 0 and sb.ninodes > 0:
            nbmapblocks = (sb.size + BPB - 1) // BPB
            datastart   = sb.bmapstart + nbmapblocks
            if datastart >= sb.size:
                self.log_error(
                    f"Filesystem too small: computed datastart={datastart} "
                    f">= total size={sb.size}; no room for data blocks"
                )

    # ------------------------------------------------------------------
    # Phase 2: Inode table and block addresses
    # ------------------------------------------------------------------
    def check_inodes_and_blocks(self, datastart, used_blocks):
        sb = self.sb

        for inum in range(1, sb.ninodes):
            inode = self.img.read_dinode(inum)

            if inode.type == T_UNUSED:
                continue

            if inode.type not in (T_DIR, T_FILE, T_DEVICE):
                self.log_error(
                    f"Inode {inum}: invalid type {inode.type} "
                    f"(expected 1=DIR, 2=FILE, 3=DEVICE)"
                )
                continue

            if inode.type == T_DIR and inode.size % DIRENT_SIZE != 0:
                self.log_error(
                    f"Directory inode {inum}: size {inode.size} is not a "
                    f"multiple of DIRENT_SIZE ({DIRENT_SIZE})"
                )

            # Direct block pointers
            for i in range(NDIRECT):
                b = inode.addrs[i]
                if b == 0:
                    continue
                if b < datastart or b >= sb.size:
                    self.log_error(
                        f"Inode {inum}: direct block[{i}] = {b} "
                        f"is out of data range [{datastart}, {sb.size})"
                    )
                else:
                    used_blocks[b].append(f"inode {inum} direct[{i}]")

            # Indirect block pointer
            indir_b = inode.addrs[NDIRECT]
            if indir_b == 0:
                continue

            if indir_b < datastart or indir_b >= sb.size:
                self.log_error(
                    f"Inode {inum}: indirect pointer block = {indir_b} "
                    f"is out of data range [{datastart}, {sb.size})"
                )
                continue

            used_blocks[indir_b].append(f"inode {inum} indirect-ptr-block")

            indir_data = self.img.read_block(indir_b)
            for j in range(NINDIRECT):
                b = struct.unpack_from("<I", indir_data, j * 4)[0]
                if b == 0:
                    continue
                if b < datastart or b >= sb.size:
                    self.log_error(
                        f"Inode {inum}: indirect block entry[{j}] = {b} "
                        f"is out of data range [{datastart}, {sb.size})"
                    )
                else:
                    used_blocks[b].append(f"inode {inum} indirect[{j}]")

        # Duplicate block check
        for b, refs in used_blocks.items():
            if len(refs) > 1:
                self.log_error(
                    f"Block {b} is allocated to multiple inodes: "
                    + ", ".join(refs)
                )

    # ------------------------------------------------------------------
    # Phase 3: Directory structure (DFS from root)
    # ------------------------------------------------------------------
    def check_directories(self, inum, expected_parent, visited_dirs,
                          inode_ref_counts, dir_subdir_counts):
        if inum in visited_dirs:
            self.log_error(f"Directory loop detected at inode {inum}")
            return
        visited_dirs.add(inum)

        inode = self.img.read_dinode(inum)
        if inode.type != T_DIR:
            self.log_error(f"Inode {inum} is expected to be a directory but has type {inode.type}")
            return

        has_dot    = False
        has_dotdot = False
        sb         = self.sb

        off = 0
        while off < inode.size:
            data = self.img.readi(inum, off, DIRENT_SIZE)
            if len(data) < DIRENT_SIZE:
                break

            de = Dirent.unpack(data)
            off += DIRENT_SIZE

            if de.inum == 0:
                continue  # empty/deleted slot

            # Guard before calling read_dinode so bad dirents don't raise ValueError
            if de.inum >= sb.ninodes:
                self.log_error(
                    f"Directory {inum}: entry '{de.name}' has inode number "
                    f"{de.inum} which is out of range (max {sb.ninodes - 1})"
                )
                continue

            if de.name == ".":
                has_dot = True
                if de.inum != inum:
                    self.log_error(
                        f"Directory {inum}: '.' entry points to inode {de.inum} "
                        f"instead of {inum}"
                    )

            elif de.name == "..":
                has_dotdot = True
                if de.inum != expected_parent:
                    self.log_error(
                        f"Directory {inum}: '..' entry points to inode {de.inum} "
                        f"instead of expected parent {expected_parent}"
                    )

            else:
                child_inode = self.img.read_dinode(de.inum)
                if child_inode.type == T_UNUSED:
                    self.log_error(
                        f"Directory {inum}: entry '{de.name}' references "
                        f"inode {de.inum} which is free (T_UNUSED)"
                    )
                elif child_inode.type == T_DIR:
                    dir_subdir_counts[inum] += 1
                    self.check_directories(de.inum, inum, visited_dirs,
                                           inode_ref_counts, dir_subdir_counts)
                else:
                    inode_ref_counts[de.inum] += 1

        if not has_dot:
            self.log_error(f"Directory {inum}: missing '.' entry")
        if not has_dotdot:
            self.log_error(f"Directory {inum}: missing '..' entry")

    # ------------------------------------------------------------------
    # Phase 4: Link counts
    # ------------------------------------------------------------------
    def check_link_counts(self, inode_ref_counts, dir_subdir_counts):
        sb = self.sb
        for inum in range(1, sb.ninodes):
            inode = self.img.read_dinode(inum)
            if inode.type == T_UNUSED:
                continue

            if inode.type == T_DIR:
                # xv6 dir nlink = 1 + subdirs ('.' is not counted)
                expected = 1 + dir_subdir_counts[inum]
                if inode.nlink != expected:
                    self.log_error(
                        f"Directory inode {inum}: nlink={inode.nlink} "
                        f"but expected {expected} "
                        f"(1 base + {dir_subdir_counts[inum]} subdirectories)"
                    )

            elif inode.type in (T_FILE, T_DEVICE):
                expected = inode_ref_counts[inum]
                if inode.nlink != expected:
                    self.log_error(
                        f"{'File' if inode.type == T_FILE else 'Device'} "
                        f"inode {inum}: nlink={inode.nlink} "
                        f"but expected {expected} directory reference(s)"
                    )

    # ------------------------------------------------------------------
    # Phase 5: Bitmap consistency
    # ------------------------------------------------------------------
    def check_bitmap(self, datastart, referenced_data_blocks):
        sb = self.sb

        allocated_in_bitmap = set()
        for base in range(0, sb.size, BPB):
            bblock      = BBLOCK(base, sb)
            bitmap_data = self.img.read_block(bblock)
            limit       = min(BPB, sb.size - base)
            for bit_pos in range(limit):
                byte_idx = bit_pos // 8
                bit_idx  = bit_pos % 8
                if (bitmap_data[byte_idx] & (1 << bit_idx)) != 0:
                    allocated_in_bitmap.add(base + bit_pos)

        # Metadata blocks (boot, superblock, log, inodes, bitmap) must all be marked used
        for b in range(datastart):
            if b not in allocated_in_bitmap:
                self.log_error(
                    f"Metadata block {b} is marked FREE in the bitmap "
                    f"(all metadata blocks must be allocated)"
                )

        # Data blocks: referenced <-> marked in bitmap
        for b in range(datastart, sb.size):
            in_use  = b in referenced_data_blocks
            in_bmap = b in allocated_in_bitmap

            if in_use and not in_bmap:
                self.log_error(
                    f"Data block {b} is referenced by an inode but is "
                    f"marked FREE in the bitmap (corruption)"
                )
            elif not in_use and in_bmap:
                self.log_error(
                    f"Data block {b} is marked USED in the bitmap but is "
                    f"not referenced by any inode (block leak)"
                )

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def _print_results(self):
        if not self.errors:
            print("fsck passed: filesystem is clean.")
            return True
        print(f"fsck found {len(self.errors)} error(s):")
        for err in self.errors:
            print(f"  - {err}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 fsck.py <fs.img>")
        sys.exit(1)

    checker = XV6Fsck(sys.argv[1])
    success = checker.run()
    sys.exit(0 if success else 1)
