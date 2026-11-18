# FUSE wrapper for mounting xv6 fs.img on Linux.

import os
import sys
import stat
import time
import errno

try:
    from fuse import FUSE, FuseOSError, Operations
except (ImportError, OSError):
    # Note to self: lets unit tests import this file even without libfuse on macOS
    Operations = object
    FuseOSError = OSError
    FUSE = None

from xv6defs import T_DIR, T_FILE
from xv6img import XV6Image
import alloc
import dirops


class XV6Fuse(Operations):
    def __init__(self, img_path):
        self.img = XV6Image(img_path)
        self.epoch = int(time.time()) # xv6 doesn't store timestamps so just use mount time

    def getattr(self, path, fh=None):
        inum = self.img.namei(path)
        if inum is None:
            raise FuseOSError(errno.ENOENT)

        ip = self.img.read_dinode(inum)
        if ip.type == T_DIR:
            # Linux expects nlink = 2 + subdirs, xv6 has 1 + subdirs (no '.' link count)
            st_nlink = ip.nlink + 1
            st_mode = stat.S_IFDIR | 0o755
        elif ip.type == T_FILE:
            st_nlink = ip.nlink
            st_mode = stat.S_IFREG | 0o644
        else:
            raise FuseOSError(errno.ENOENT)

        return {
            'st_mode': st_mode,
            'st_nlink': st_nlink,
            'st_size': ip.size,
            'st_ctime': self.epoch,
            'st_mtime': self.epoch,
            'st_atime': self.epoch,
            'st_uid': os.getuid() if hasattr(os, 'getuid') else 1000,
            'st_gid': os.getgid() if hasattr(os, 'getgid') else 1000,
        }

    def readdir(self, path, fh):
        inum = self.img.namei(path)
        if inum is None:
            raise FuseOSError(errno.ENOENT)

        seen = set()
        for _, name in self.img.get_dirents(inum):
            if name not in seen:
                seen.add(name)
                yield name

    def read(self, path, size, offset, fh):
        inum = self.img.namei(path)
        if inum is None:
            raise FuseOSError(errno.ENOENT)
        return self.img.readi(inum, offset, size)

    def write(self, path, data, offset, fh):
        inum = self.img.namei(path)
        if inum is None:
            raise FuseOSError(errno.ENOENT)
        try:
            return alloc.writei(self.img, inum, data, offset)
        except OSError as e:
            raise FuseOSError(e.errno)

    def create(self, path, mode, fi=None):
        try:
            return dirops.create(self.img, path, type_=T_FILE)
        except OSError as e:
            raise FuseOSError(e.errno)

    def mkdir(self, path, mode):
        try:
            dirops.mkdir(self.img, path)
        except OSError as e:
            raise FuseOSError(e.errno)

    def unlink(self, path):
        try:
            dirops.unlink(self.img, path)
        except OSError as e:
            raise FuseOSError(e.errno)

    # xv6 unlink already handles empty dirs
    def rmdir(self, path):
        try:
            dirops.unlink(self.img, path)
        except OSError as e:
            raise FuseOSError(e.errno)

    def truncate(self, path, length, fh=None):
        inum = self.img.namei(path)
        if inum is None:
            raise FuseOSError(errno.ENOENT)
        try:
            alloc.truncate(self.img, inum, length)
        except OSError as e:
            raise FuseOSError(e.errno)

    # xv6 has no permissions/ownership/times; stub these out so cp/touch work cleanly
    def chmod(self, path, mode):
        return 0

    def chown(self, path, uid, gid):
        return 0

    def utimens(self, path, times=None):
        return 0


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 xv6fuse.py <fs.img> <mountpoint> [-f]")
        sys.exit(1)

    img_path = sys.argv[1]
    mountpoint = sys.argv[2]
    fg = "-f" in sys.argv

    if FUSE is None:
        print("Error: fusepy is not installed (or libfuse is missing). Install with 'pip install fusepy'")
        sys.exit(1)

    print(f"Mounting {img_path} at {mountpoint} (foreground={fg})...")
    FUSE(XV6Fuse(img_path), mountpoint, nothreads=True, foreground=fg)


if __name__ == '__main__':
    main()
