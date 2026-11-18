# Tests for fsck.py consistency checker.
# Injects raw binary corruptions directly into temp images to exercise each check.

import os
import struct
import tempfile
import unittest

from xv6defs import (
    BSIZE, BPB, IPB, FSMAGIC, ROOTINO,
    T_UNUSED, T_DIR, T_FILE, T_DEVICE,
    NDIRECT, DIRENT_SIZE, DIRENT_FORMAT,
    DINODE_FORMAT, DINODE_SIZE, SUPERBLOCK_FORMAT
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

# Derived layout constants (must match create_empty_image)
LOGSTART   = 2
INODESTART = LOGSTART + NLOG              # 32
NINODEBLKS = (NINODES + IPB - 1) // IPB   # 7
BMAPSTART  = INODESTART + NINODEBLKS      # 39
NBMAPBLKS  = (NBLOCKS + BPB - 1) // BPB   # 1
DATASTART  = BMAPSTART + NBMAPBLKS        # 40

SB_OFFSET  = 1 * BSIZE                    # block 1


# ---------------------------------------------------------------------------
# Low-level binary helpers (write directly to the image file)
# ---------------------------------------------------------------------------

def _read_sb_fields(path):
    with open(path, "rb") as f:
        f.seek(SB_OFFSET)
        data = f.read(struct.calcsize(SUPERBLOCK_FORMAT))
    keys = ("magic", "size", "nblocks", "ninodes",
            "nlog", "logstart", "inodestart", "bmapstart")
    return dict(zip(keys, struct.unpack(SUPERBLOCK_FORMAT, data)))


def _write_sb_field(path, **kwargs):
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


def _inode_offset(inum):
    block = (inum // IPB) + INODESTART
    return block * BSIZE + (inum % IPB) * DINODE_SIZE


def _read_inode_raw(path, inum):
    with open(path, "rb") as f:
        f.seek(_inode_offset(inum))
        data = f.read(DINODE_SIZE)
    vals = struct.unpack(DINODE_FORMAT, data)
    return {
        "type": vals[0], "major": vals[1], "minor": vals[2],
        "nlink": vals[3], "size": vals[4],
        "addrs": list(vals[5:])
    }


def _write_inode_raw(path, inum, **fields):
    cur = _read_inode_raw(path, inum)
    cur.update(fields)
    packed = struct.pack(DINODE_FORMAT,
                         cur["type"], cur["major"], cur["minor"],
                         cur["nlink"], cur["size"],
                         *cur["addrs"])
    with open(path, "r+b") as f:
        f.seek(_inode_offset(inum))
        f.write(packed)


def _bitmap_byte_offset(block_num):
    bblock      = (block_num // BPB) + BMAPSTART
    bit_in_bmap = block_num % BPB
    file_offset = bblock * BSIZE + bit_in_bmap // 8
    bit_index   = bit_in_bmap % 8
    return file_offset, bit_index


def _clear_bitmap_bit(path, block_num):
    file_offset, bit_index = _bitmap_byte_offset(block_num)
    with open(path, "r+b") as f:
        f.seek(file_offset)
        byte = f.read(1)[0]
        byte &= ~(1 << bit_index) & 0xFF
        f.seek(file_offset)
        f.write(bytes([byte]))


def _set_bitmap_bit(path, block_num):
    file_offset, bit_index = _bitmap_byte_offset(block_num)
    with open(path, "r+b") as f:
        f.seek(file_offset)
        byte = f.read(1)[0]
        byte |= (1 << bit_index)
        f.seek(file_offset)
        f.write(bytes([byte]))


def _write_dirent(path, block_num, slot, inum, name):
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
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".img")
        self.temp_path = tmp.name
        tmp.close()
        create_empty_image(self.temp_path, nblocks=NBLOCKS, ninodes=NINODES)

    def tearDown(self):
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def _run_fsck(self):
        checker = XV6Fsck(self.temp_path)
        return checker.run()

    # -----------------------------------------------------------------------
    # Positive tests - clean / valid filesystems
    # -----------------------------------------------------------------------

    def test_clean_image_passes(self):
        self.assertTrue(self._run_fsck())

    def test_after_files_and_directories_passes(self):
        img = XV6Image(self.temp_path)
        dirops.mkdir(img, "/docs")
        f1 = dirops.create(img, "/docs/readme.txt", T_FILE)
        alloc.writei(img, f1, b"Consistency check test data\n", 0)
        img.close()
        self.assertTrue(self._run_fsck())

    def test_nested_directories_pass(self):
        img = XV6Image(self.temp_path)
        dirops.mkdir(img, "/a")
        dirops.mkdir(img, "/a/b")
        dirops.mkdir(img, "/a/b/c")
        dirops.create(img, "/a/b/c/file.txt", T_FILE)
        img.close()
        self.assertTrue(self._run_fsck())

    def test_large_file_with_indirect_blocks_passes(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/bigfile", T_FILE)
        # spill past the 12 direct blocks (12 * 1024 = 12288 bytes)
        data = b"X" * BSIZE
        for _ in range(NDIRECT + 2):
            alloc.writei(img, f1, data, img.read_dinode(f1).size)
        img.close()
        self.assertTrue(self._run_fsck())

    def test_hard_links_pass(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/original.txt", T_FILE)
        alloc.writei(img, f1, b"shared content", 0)
        dirops.link(img, "/original.txt", "/linked.txt")
        img.close()
        self.assertTrue(self._run_fsck())

    def test_multiple_files_in_directory_pass(self):
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
        _write_sb_field(self.temp_path, magic=0xDEADBEEF)
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)
        self.assertTrue(any("magic" in e.lower() or "open" in e.lower()
                            for e in checker.errors))

    def test_invalid_filesystem_size(self):
        _write_sb_field(self.temp_path, magic=FSMAGIC, size=0)
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    def test_invalid_inode_count(self):
        _write_sb_field(self.temp_path, ninodes=0)
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    def test_superblock_inverted_logstart(self):
        _write_sb_field(self.temp_path, logstart=0)
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    def test_superblock_inverted_field_ordering(self):
        # put bmapstart before inodestart
        _write_sb_field(self.temp_path, bmapstart=INODESTART - 1)
        checker = XV6Fsck(self.temp_path)
        result = checker.run()
        self.assertFalse(result)

    # -----------------------------------------------------------------------
    # Inode corruption tests
    # -----------------------------------------------------------------------

    def test_invalid_inode_type(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        img.close()
        _write_inode_raw(self.temp_path, f1, type=99)
        self.assertFalse(self._run_fsck())

    def test_direct_block_out_of_range(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        alloc.writei(img, f1, b"hello", 0)
        img.close()
        addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        addrs[0] = NBLOCKS + 999
        _write_inode_raw(self.temp_path, f1, addrs=addrs)
        self.assertFalse(self._run_fsck())

    def test_direct_block_in_metadata_range(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        alloc.writei(img, f1, b"hello", 0)
        img.close()
        addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        addrs[0] = 1   # block 1 is the superblock
        _write_inode_raw(self.temp_path, f1, addrs=addrs)
        self.assertFalse(self._run_fsck())

    def test_indirect_block_pointer_out_of_range(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/victim.txt", T_FILE)
        img.close()
        addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        addrs[NDIRECT] = NBLOCKS + 500
        _write_inode_raw(self.temp_path, f1, addrs=addrs)
        self.assertFalse(self._run_fsck())

    def test_duplicate_block_allocation(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/file1.txt", T_FILE)
        f2 = dirops.create(img, "/file2.txt", T_FILE)
        alloc.writei(img, f1, b"aaa", 0)
        alloc.writei(img, f2, b"bbb", 0)
        img.close()
        # point f2's direct[0] at f1's block
        f1_addrs = _read_inode_raw(self.temp_path, f1)["addrs"]
        f2_addrs = _read_inode_raw(self.temp_path, f2)["addrs"]
        f2_addrs[0] = f1_addrs[0]
        _write_inode_raw(self.temp_path, f2, addrs=f2_addrs)
        self.assertFalse(self._run_fsck())

    def test_file_nlink_mismatch(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/lone.txt", T_FILE)
        img.close()
        _write_inode_raw(self.temp_path, f1, nlink=5)
        self.assertFalse(self._run_fsck())

    def test_directory_nlink_mismatch(self):
        img = XV6Image(self.temp_path)
        d1 = dirops.mkdir(img, "/mydir")
        img.close()
        _write_inode_raw(self.temp_path, d1, nlink=7)
        self.assertFalse(self._run_fsck())

    def test_device_inode_nlink_mismatch(self):
        img = XV6Image(self.temp_path)
        dev_inum = dirops.create(img, "/console", T_DEVICE, major=1, minor=1)
        img.close()
        _write_inode_raw(self.temp_path, dev_inum, nlink=99)
        self.assertFalse(self._run_fsck())

    # -----------------------------------------------------------------------
    # Bitmap corruption tests
    # -----------------------------------------------------------------------

    def test_bitmap_inode_block_marked_free(self):
        _clear_bitmap_bit(self.temp_path, INODESTART)
        self.assertFalse(self._run_fsck())

    def test_bitmap_data_block_referenced_but_free(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/hello.txt", T_FILE)
        alloc.writei(img, f1, b"data", 0)
        img.close()
        data_block = _read_inode_raw(self.temp_path, f1)["addrs"][0]
        _clear_bitmap_bit(self.temp_path, data_block)
        self.assertFalse(self._run_fsck())

    def test_bitmap_leaked_block(self):
        free_data_block = DATASTART + 1   # unused in an empty image
        _set_bitmap_bit(self.temp_path, free_data_block)
        self.assertFalse(self._run_fsck())

    # -----------------------------------------------------------------------
    # Directory structure corruption tests
    # -----------------------------------------------------------------------

    def test_dot_entry_wrong_target(self):
        # root data is at DATASTART; slot 0 is '.'
        _write_dirent(self.temp_path, DATASTART, slot=0, inum=2, name=".")
        self.assertFalse(self._run_fsck())

    def test_dotdot_entry_wrong_target(self):
        img = XV6Image(self.temp_path)
        d1 = dirops.mkdir(img, "/child")
        img.close()
        child_data_block = _read_inode_raw(self.temp_path, d1)["addrs"][0]
        _write_dirent(self.temp_path, child_data_block, slot=1, inum=99, name="..")
        self.assertFalse(self._run_fsck())

    def test_missing_dot_entry(self):
        _write_dirent(self.temp_path, DATASTART, slot=0, inum=0, name="\x00")
        self.assertFalse(self._run_fsck())

    def test_missing_dotdot_entry(self):
        _write_dirent(self.temp_path, DATASTART, slot=1, inum=0, name="\x00")
        self.assertFalse(self._run_fsck())

    def test_dirent_references_unused_inode(self):
        img = XV6Image(self.temp_path)
        f1 = dirops.create(img, "/orphan.txt", T_FILE)
        img.close()
        _write_inode_raw(self.temp_path, f1, type=T_UNUSED, nlink=0)
        self.assertFalse(self._run_fsck())

    def test_dirent_inum_out_of_range(self):
        """A dirent with inum >= ninodes should report an error instead of crashing."""
        _write_dirent(self.temp_path, DATASTART, slot=2, inum=999, name="bad")
        cur = _read_inode_raw(self.temp_path, ROOTINO)
        _write_inode_raw(self.temp_path, ROOTINO, size=cur["size"] + DIRENT_SIZE)
        self.assertFalse(self._run_fsck())


if __name__ == "__main__":
    unittest.main()
