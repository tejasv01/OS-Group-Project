"""
tests/test_fsck.py - Comprehensive tests for the fsck consistency checker.

Each test creates a fresh temporary filesystem image, optionally corrupts it
at the binary level, then runs XV6Fsck.run() and asserts the expected outcome.

Corruption helpers write directly into the image file so we can inject errors
that the higher-level filesystem code (alloc / dirops) would never produce.
"""

import os
import struct
import tempfile
import unittest

from xv6defs import (
    BSIZE, BPB, IPB, FSMAGIC, ROOTINO,
    T_UNUSED, T_DIR, T_FILE, T_DEVICE,
    NDIRECT, NINDIRECT, DIRENT_SIZE, DIRENT_FORMAT,
    DINODE_FORMAT, DINODE_SIZE, SUPERBLOCK_FORMAT,
    Dinode, Dirent, IBLOCK, BBLOCK
)
from xv6img import XV6Image, create_empty_image
from fsck import XV6Fsck
import alloc
import dirops


# ---------------------------------------------------------------------------
# Standard image parameters used by every test
# ---------------------------------------------------------------------------
NBLOCKS  = 1000
NINODES  = 100
NLOG     = 30

# Derived layout constants (must match create_empty_image logic)
LOGSTART   = 2
INODESTART = LOGSTART + NLOG          # 32
NINODEBLKS = (NINODES + IPB - 1) // IPB   # 7
BMAPSTART  = INODESTART + NINODEBLKS   # 39
NBMAPBLKS  = (NBLOCKS  + BPB - 1) // BPB # 1
DATASTART  = BMAPSTART + NBMAPBLKS    # 40

SB_OFFSET  = 1 * BSIZE               # superblock starts at byte 1024


# ---------------------------------------------------------------------------
# Low-level binary helpers (write directly to the image file)
# ---------------------------------------------------------------------------

def _read_sb_fields(path: str) -> dict:
    """Return the superblock as a plain dict."""
    with open(path, "rb") as f:
        f.seek(SB_OFFSET)
        data = f.read(struct.calcsize(SUPERBLOCK_FORMAT))
    keys = ("magic", "size", "nblocks", "ninodes",
            "nlog", "logstart", "inodestart", "bmapstart")
    return dict(zip(keys, struct.unpack(SUPERBLOCK_FORMAT, data)))


def _write_sb_field(path: str, **kwargs):
    """Overwrite individual superblock fields by name."""
    fields = _read_sb_fields(path)
    fields.update(kwargs)
    packed = struct.pack(SUPERBLOCK_FORMAT,
                         fields["magic"],   fields["size"],
                         fields["nblocks"], fields["ninodes"],
                         fields["nlog"],    fields["logstart"],
                         fields["inodestart"], fields["bmapstart"])
    with open(path, "r+b") as f:
        f.seek(SB_OFFSET)
        f.write(packed)


def _inode_offset(inum: int) -> int:
    """Byte offset of inode `inum` within the image file."""
    block = (inum // IPB) + INODESTART
    return block * BSIZE + (inum % IPB) * DINODE_SIZE


def _read_inode_raw(path: str, inum: int) -> dict:
    """Read and return inode fields as a plain dict."""
    with open(path, "rb") as f:
        f.seek(_inode_offset(inum))
        data = f.read(DINODE_SIZE)
    vals = struct.unpack(DINODE_FORMAT, data)
    return {
        "type": vals[0], "major": vals[1], "minor": vals[2],
        "nlink": vals[3], "size": vals[4],
        "addrs": list(vals[5:])
    }


def _write_inode_raw(path: str, inum: int, **fields):
    """Overwrite individual fields of an on-disk inode."""
    cur = _read_inode_raw(path, inum)
    cur.update(fields)
    packed = struct.pack(DINODE_FORMAT,
                         cur["type"], cur["major"], cur["minor"],
                         cur["nlink"], cur["size"],
                         *cur["addrs"])
    with open(path, "r+b") as f:
        f.seek(_inode_offset(inum))
        f.write(packed)


def _bitmap_byte_offset(block_num: int) -> tuple:
    """Return (file_offset, bit_index) for block_num's bitmap entry."""
    bblock      = (block_num // BPB) + BMAPSTART
    bit_in_bmap = block_num % BPB
    file_offset = bblock * BSIZE + bit_in_bmap // 8
    bit_index   = bit_in_bmap % 8
    return file_offset, bit_index


def _clear_bitmap_bit(path: str, block_num: int):
    """Mark block_num as FREE in the bitmap (clear its bit)."""
    file_offset, bit_index = _bitmap_byte_offset(block_num)
    with open(path, "r+b") as f:
        f.seek(file_offset)
        byte = f.read(1)[0]
        byte &= ~(1 << bit_index) & 0xFF
        f.seek(file_offset)
        f.write(bytes([byte]))


def _set_bitmap_bit(path: str, block_num: int):
    """Mark block_num as USED in the bitmap (set its bit)."""
    file_offset, bit_index = _bitmap_byte_offset(block_num)
    with open(path, "r+b") as f:
        f.seek(file_offset)
        byte = f.read(1)[0]
        byte |= (1 << bit_index)
        f.seek(file_offset)
        f.write(bytes([byte]))


def _write_dirent(path: str, block_num: int, slot: int, inum: int, name: str):
    """Overwrite a single directory entry in a data block."""
    encoded = name.encode("latin1")[:14].ljust(14, b"\x00")
    packed  = struct.pack(DIRENT_FORMAT, inum, encoded)
    offset  = block_num * BSIZE + slot * DIRENT_SIZE
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(packed)


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestFsck(unittest.TestCase):

    def setUp(self):
        """Create a fresh temporary filesystem image before each test."""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".img")
        self.temp_path = tmp.name
        tmp.close()
        create_empty_image(self.temp_path, nblocks=NBLOCKS, ninodes=NINODES)

    def tearDown(self):
        """Remove the temporary image after each test."""
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def _run_fsck(self) -> bool:
        checker = XV6Fsck(self.temp_path)
        return checker.run()

    # -----------------------------------------------------------------------
    # Positive tests – clean / valid filesystems
    # -----------------------------------------------------------------------

    def test_clean_image_passes(self):
        """A freshly created empty image must pass all checks."""
        self.assertTrue(self._run_fsck())

    def test_after_files_and_directories_passes(self):
        """Creating a directory and a file, then writing data, stays clean."""
        img = XV6Image(self.temp_path)
        d1 = dirops.mkdir(img, "/docs")
        f1 = dirops.create(img, "/docs/readme.txt", T_FILE)
        alloc.writei(img, f1, b"Consistency check test data\n", 0)
        img.close()
        self.assertTrue(self._run_fsck())

    def test_nested_directories_pass(self):
        """Several levels of nested directories remain consistent."""
        img = XV6Image(self.temp_path)
        dirops.mkdir(img, "/a")
        dirops.mkdir(img, "/a/b")
        dirops.mkdir(img, "/a/b/c")
        dirops.create(img, "/a/b/c/file.txt", T_FILE)
        img.close()
        self.assertTrue(self._run_fsck())

    def test_large_file_with_indirect_blocks_passes(self):
        """A file large enough to use the indirect block must still pass."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/bigfile", T_FILE)
        # Write enough to spill past the 12 direct blocks (12 * 1024 = 12 288 bytes).
        data = b"X" * BSIZE
        for _ in range(NDIRECT + 2):
            alloc.writei(img, f1, data, img.read_dinode(f1).size)
        img.close()
        self.assertTrue(self._run_fsck())

    def test_hard_links_pass(self):
        """A file with two directory entries (hard link) must have nlink==2."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/original.txt", T_FILE)
        alloc.writei(img, f1, b"shared content", 0)
        dirops.link(img, "/original.txt", "/linked.txt")
        img.close()
        self.assertTrue(self._run_fsck())

    def test_multiple_files_in_directory_pass(self):
        """Multiple files and directories in root all stay consistent."""
        img = XV6Image(self.temp_path)
        for i in range(5):
            dirops.create(img, f"/file{i}.txt", T_FILE)
        dirops.mkdir(img, "/subdir")
        img.close()
        self.assertTrue(self._run_fsck())

    # -----------------------------------------------------------------------
    # Superblock corruption tests
    # -----------------------------------------------------------------------

    def test_bad_magic_number(self):
        """A wrong magic number must be caught immediately."""
        _write_sb_field(self.temp_path, magic=0xDEADBEEF)
        # XV6Image raises ValueError on open (bad magic); fsck catches it.
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)
        self.assertTrue(any("magic" in e.lower() or "open" in e.lower()
                            for e in checker.errors))

    def test_invalid_filesystem_size(self):
        """A superblock with size=0 must be rejected."""
        _write_sb_field(self.temp_path, magic=FSMAGIC, size=0)
        # XV6Image.read_block will likely fail or fsck.check_superblock catches it.
        # Either way the checker must return False.
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    def test_invalid_inode_count(self):
        """A superblock with ninodes=0 must be rejected."""
        _write_sb_field(self.temp_path, ninodes=0)
        # Re-open with valid magic so XV6Image doesn't raise – the checker
        # itself should catch ninodes=0.
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    def test_superblock_inverted_logstart(self):
        """logstart < 2 is structurally invalid."""
        _write_sb_field(self.temp_path, logstart=0)
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    def test_superblock_inverted_field_ordering(self):
        """bmapstart <= inodestart is structurally invalid."""
        # Put bmapstart before inodestart (nonsense layout)
        _write_sb_field(self.temp_path, bmapstart=INODESTART - 1)
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    # -----------------------------------------------------------------------
    # Inode corruption tests
    # -----------------------------------------------------------------------

    def test_invalid_inode_type(self):
        """An inode with type=99 (not DIR/FILE/DEVICE/UNUSED) is an error."""
        # Create a file so we have a used inode to corrupt.
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        img.close()
        _write_inode_raw(self.temp_path, f1, type=99)
        self.assertFalse(self._run_fsck())

    def test_direct_block_out_of_range(self):
        """An inode whose direct block pointer exceeds sb.size is an error."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        alloc.writei(img, f1, b"hello", 0)
        img.close()
        # Corrupt direct block[0] to an impossible value.
        addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        addrs[0] = NBLOCKS + 999   # well beyond sb.size
        _write_inode_raw(self.temp_path, f1, addrs=addrs)
        self.assertFalse(self._run_fsck())

    def test_direct_block_in_metadata_range(self):
        """An inode direct block pointing into metadata area (< datastart) is bad."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        alloc.writei(img, f1, b"hello", 0)
        img.close()
        addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        addrs[0] = 1   # block 1 is the superblock – clearly metadata
        _write_inode_raw(self.temp_path, f1, addrs=addrs)
        self.assertFalse(self._run_fsck())

    def test_indirect_block_pointer_out_of_range(self):
        """An indirect pointer block address beyond sb.size is an error."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        img.close()
        addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        addrs[NDIRECT] = NBLOCKS + 500   # out of range
        _write_inode_raw(self.temp_path, f1, addrs=addrs)
        self.assertFalse(self._run_fsck())

    def test_duplicate_block_allocation(self):
        """Two inodes sharing the same data block is a double-allocation error."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/file1.txt", T_FILE)
        f2 = dirops.create(img, "/file2.txt", T_FILE)
        alloc.writei(img, f1, b"aaa", 0)
        alloc.writei(img, f2, b"bbb", 0)
        img.close()
        # Find f1's data block and jam it into f2's direct[0].
        f1_addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        f2_addrs = _read_inode_raw(self.temp_path, f2)["addrs"]
        shared_block = f1_addrs[0]
        f2_addrs[0]  = shared_block
        _write_inode_raw(self.temp_path, f2, addrs=f2_addrs)
        self.assertFalse(self._run_fsck())

    def test_file_nlink_mismatch(self):
        """A file whose on-disk nlink doesn't match directory references is bad."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/lone.txt", T_FILE)
        img.close()
        # The file has 1 directory reference, so nlink should be 1.
        # Setting it to 5 is a mismatch.
        _write_inode_raw(self.temp_path, f1, nlink=5)
        self.assertFalse(self._run_fsck())

    def test_directory_nlink_mismatch(self):
        """A directory whose nlink doesn't match 1+subdirs is bad."""
        img = XV6Image(self.temp_path)
        d1 = dirops.mkdir(img, "/mydir")
        img.close()
        # /mydir has 0 subdirs, so nlink should be 1; set it to 7.
        _write_inode_raw(self.temp_path, d1, nlink=7)
        self.assertFalse(self._run_fsck())

    def test_device_inode_nlink_mismatch(self):
        """A T_DEVICE inode with wrong nlink should be caught."""
        # Manually inject a device inode into inode slot 2 (unused) and
        # write a directory entry in root pointing to it.
        img = XV6Image(self.temp_path)
        # Use create with T_DEVICE to allocate properly.
        dev_inum = dirops.create(img, "/console", T_DEVICE, major=1, minor=1)
        img.close()
        # The device has 1 reference (the /console entry); set nlink wrong.
        _write_inode_raw(self.temp_path, dev_inum, nlink=99)
        self.assertFalse(self._run_fsck())

    # -----------------------------------------------------------------------
    # Bitmap corruption tests
    # -----------------------------------------------------------------------

    def test_bitmap_inode_block_marked_free(self):
        """Clearing the bitmap bit of a metadata block is a bitmap error."""
        # Block INODESTART is a metadata (inode table) block.
        _clear_bitmap_bit(self.temp_path, INODESTART)
        self.assertFalse(self._run_fsck())

    def test_bitmap_data_block_referenced_but_free(self):
        """A block used by an inode but marked FREE in the bitmap is an error."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/hello.txt", T_FILE)
        alloc.writei(img, f1, b"data", 0)
        img.close()
        data_block = _read_inode_raw(self.temp_path, f1)["addrs"][0]
        _clear_bitmap_bit(self.temp_path, data_block)
        self.assertFalse(self._run_fsck())

    def test_bitmap_leaked_block(self):
        """A data block that is marked USED but referenced by no inode is a leak."""
        # Find the first free data block and set its bitmap bit without
        # giving it to any inode.
        free_data_block = DATASTART + 1   # block 41 is free in an empty image
        _set_bitmap_bit(self.temp_path, free_data_block)
        self.assertFalse(self._run_fsck())

    # -----------------------------------------------------------------------
    # Directory structure corruption tests
    # -----------------------------------------------------------------------

    def test_dot_entry_wrong_target(self):
        """The '.' entry in a directory must point to the directory itself."""
        # Corrupt root's '.' to point to inode 2 instead of ROOTINO (1).
        # Root data is at block DATASTART (40); slot 0 is '.'.
        _write_dirent(self.temp_path, DATASTART, slot=0,
                      inum=2, name=".")
        self.assertFalse(self._run_fsck())

    def test_dotdot_entry_wrong_target(self):
        """The '..' entry must point to the parent directory."""
        img = XV6Image(self.temp_path)
        d1 = dirops.mkdir(img, "/child")
        img.close()
        # Find child's data block and corrupt its '..' (slot 1) to point to 99.
        child_addrs = _read_inode_raw(self.temp_path, d1)["addrs"]
        child_data_block = child_addrs[0]
        _write_dirent(self.temp_path, child_data_block, slot=1,
                      inum=99, name="..")
        self.assertFalse(self._run_fsck())

    def test_missing_dot_entry(self):
        """A directory without a '.' entry must be flagged."""
        # Zero out root's '.' slot (slot 0 in block DATASTART).
        _write_dirent(self.temp_path, DATASTART, slot=0, inum=0, name="\x00")
        self.assertFalse(self._run_fsck())

    def test_missing_dotdot_entry(self):
        """A directory without a '..' entry must be flagged."""
        # Zero out root's '..' slot (slot 1 in block DATASTART).
        _write_dirent(self.temp_path, DATASTART, slot=1, inum=0, name="\x00")
        self.assertFalse(self._run_fsck())

    def test_dirent_references_unused_inode(self):
        """A directory entry pointing to a T_UNUSED inode is an error."""
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/orphan.txt", T_FILE)
        img.close()
        # Mark f1's inode as free (T_UNUSED) but leave the directory entry.
        _write_inode_raw(self.temp_path, f1, type=T_UNUSED, nlink=0)
        self.assertFalse(self._run_fsck())

    def test_dirent_inum_out_of_range(self):
        """A directory entry with inum >= ninodes must not crash fsck."""
        # Write an extra dirent in root's data block pointing to inum=999 (>ninodes).
        # We append it after the two existing entries (slot 2).
        _write_dirent(self.temp_path, DATASTART, slot=2,
                      inum=999, name="bad")
        # Also increase root inode's size so fsck reads slot 2.
        cur = _read_inode_raw(self.temp_path, ROOTINO)
        _write_inode_raw(self.temp_path, ROOTINO,
                         size=cur["size"] + DIRENT_SIZE)
        self.assertFalse(self._run_fsck())


if __name__ == "__main__":
    unittest.main()
