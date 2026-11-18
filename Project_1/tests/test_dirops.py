# Unit tests for dirops.py (mkdir, create, unlink, link, slot reuse, nlink rules)

import os
import tempfile
import unittest
import errno

from xv6defs import (
    ROOTINO, T_DIR, T_FILE, T_UNUSED, DIRSIZ, DIRENT_SIZE
)
from xv6img import XV6Image, create_empty_image
import alloc
import dirops


class TestDirops(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        self.temp_path = tmp.name
        tmp.close()

        create_empty_image(self.temp_path, nblocks=1000, ninodes=100)
        self.img = XV6Image(self.temp_path)

    def tearDown(self):
        self.img.close()
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_initial_root_directory(self):
        root = self.img.read_dinode(ROOTINO)
        self.assertEqual(root.type, T_DIR)
        self.assertEqual(root.nlink, 1)

        entries = {name: inum for inum, name in self.img.get_dirents(ROOTINO)}
        self.assertIn(".", entries)
        self.assertIn("..", entries)
        self.assertEqual(entries["."], ROOTINO)
        self.assertEqual(entries[".."], ROOTINO)

    def test_mkdir_and_nlink_conventions(self):
        # child nlink stays 1 ('.' not counted), parent goes up by 1 for '..'
        child_inum = dirops.mkdir(self.img, "/subdir")
        self.assertGreater(child_inum, 1)

        child = self.img.read_dinode(child_inum)
        self.assertEqual(child.type, T_DIR)
        self.assertEqual(child.nlink, 1)

        root = self.img.read_dinode(ROOTINO)
        self.assertEqual(root.nlink, 2)

        child_entries = {name: inum for inum, name in self.img.get_dirents(child_inum)}
        self.assertEqual(child_entries["."], child_inum)
        self.assertEqual(child_entries[".."], ROOTINO)

    def test_nested_subdirectories(self):
        """Parent nlink should track 1 + number of subdirs."""
        d1 = dirops.mkdir(self.img, "/d1")
        d2 = dirops.mkdir(self.img, "/d1/d2")
        d3 = dirops.mkdir(self.img, "/d1/d3")

        self.assertEqual(self.img.read_dinode(ROOTINO).nlink, 2)
        self.assertEqual(self.img.read_dinode(d1).nlink, 3)
        self.assertEqual(self.img.read_dinode(d2).nlink, 1)
        self.assertEqual(self.img.read_dinode(d3).nlink, 1)

    def test_create_regular_file(self):
        file_inum = dirops.create(self.img, "/hello.txt", T_FILE)
        f_inode = self.img.read_dinode(file_inum)
        self.assertEqual(f_inode.type, T_FILE)
        self.assertEqual(f_inode.nlink, 1)

        # files don't have '..', so root nlink shouldn't change
        root = self.img.read_dinode(ROOTINO)
        self.assertEqual(root.nlink, 1)

        payload = b"hello xv6 test"
        alloc.writei(self.img, file_inum, payload, 0)
        got = self.img.readi(file_inum, 0, len(payload))
        self.assertEqual(got, payload)

    def test_unlink_regular_file(self):
        file_inum = dirops.create(self.img, "/remove_me.txt", T_FILE)
        alloc.writei(self.img, file_inum, b"some temp data", 0)

        self.assertIsNotNone(self.img.namei("/remove_me.txt"))

        ret = dirops.unlink(self.img, "/remove_me.txt")
        self.assertEqual(ret, 0)
        self.assertIsNone(self.img.namei("/remove_me.txt"))

        inode = self.img.read_dinode(file_inum)
        self.assertEqual(inode.type, T_UNUSED)

    def test_unlink_empty_directory(self):
        dir_inum = dirops.mkdir(self.img, "/emptydir")
        self.assertEqual(self.img.read_dinode(ROOTINO).nlink, 2)

        ret = dirops.unlink(self.img, "/emptydir")
        self.assertEqual(ret, 0)

        self.assertEqual(self.img.read_dinode(ROOTINO).nlink, 1)
        self.assertEqual(self.img.read_dinode(dir_inum).type, T_UNUSED)
        self.assertIsNone(self.img.namei("/emptydir"))

    def test_unlink_non_empty_directory_fails(self):
        dirops.mkdir(self.img, "/dir_with_file")
        dirops.create(self.img, "/dir_with_file/inner.txt", T_FILE)

        with self.assertRaises(OSError) as ctx:
            dirops.unlink(self.img, "/dir_with_file")
        self.assertEqual(ctx.exception.errno, errno.ENOTEMPTY)

        self.assertEqual(self.img.read_dinode(ROOTINO).nlink, 2)
        self.assertIsNotNone(self.img.namei("/dir_with_file/inner.txt"))

    def test_unlink_dot_and_dotdot_fails(self):
        dirops.mkdir(self.img, "/mydir")

        with self.assertRaises(OSError) as ctx:
            dirops.unlink(self.img, "/mydir/.")
        self.assertEqual(ctx.exception.errno, errno.EINVAL)

        with self.assertRaises(OSError) as ctx:
            dirops.unlink(self.img, "/mydir/..")
        self.assertEqual(ctx.exception.errno, errno.EINVAL)

    def test_dirlink_slot_reuse(self):
        """Deleted dirent slots (inum == 0) should be reused instead of growing the dir."""
        dirops.mkdir(self.img, "/slot_test")
        dp_inum = self.img.namei("/slot_test")

        dirops.create(self.img, "/slot_test/file1", T_FILE)
        dirops.create(self.img, "/slot_test/file2", T_FILE)
        dirops.create(self.img, "/slot_test/file3", T_FILE)

        # 5 entries: ., .., file1, file2, file3
        size_before = self.img.read_dinode(dp_inum).size
        self.assertEqual(size_before, 5 * DIRENT_SIZE)

        dirops.unlink(self.img, "/slot_test/file2")
        dirops.create(self.img, "/slot_test/file4", T_FILE)

        size_after = self.img.read_dinode(dp_inum).size
        self.assertEqual(size_after, size_before)
        self.assertIsNotNone(self.img.namei("/slot_test/file4"))

    def test_filename_length_limits(self):
        valid_name = "a" * DIRSIZ
        too_long = "b" * (DIRSIZ + 1)

        inum = dirops.create(self.img, f"/{valid_name}", T_FILE)
        self.assertGreater(inum, 1)
        self.assertIsNotNone(self.img.namei(f"/{valid_name}"))

        with self.assertRaises(OSError) as ctx:
            dirops.create(self.img, f"/{too_long}", T_FILE)
        self.assertEqual(ctx.exception.errno, errno.ENAMETOOLONG)

    def test_duplicate_creation_fails(self):
        dirops.mkdir(self.img, "/unique")
        with self.assertRaises(OSError) as ctx:
            dirops.mkdir(self.img, "/unique")
        self.assertEqual(ctx.exception.errno, errno.EEXIST)

    def test_hard_link_and_multi_unlink(self):
        f_inum = dirops.create(self.img, "/orig.txt", T_FILE)
        alloc.writei(self.img, f_inum, b"shared file content", 0)

        ret = dirops.link(self.img, "/orig.txt", "/linked.txt")
        self.assertEqual(ret, 0)
        self.assertEqual(self.img.read_dinode(f_inum).nlink, 2)

        dirops.unlink(self.img, "/orig.txt")
        self.assertIsNone(self.img.namei("/orig.txt"))

        # still alive while linked.txt exists
        inode = self.img.read_dinode(f_inum)
        self.assertEqual(inode.type, T_FILE)
        self.assertEqual(inode.nlink, 1)
        self.assertEqual(self.img.readi(f_inum, 0, 19), b"shared file content")

        dirops.unlink(self.img, "/linked.txt")
        self.assertIsNone(self.img.namei("/linked.txt"))
        self.assertEqual(self.img.read_dinode(f_inum).type, T_UNUSED)


if __name__ == '__main__':
    unittest.main()
