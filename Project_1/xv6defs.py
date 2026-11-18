# On-disk structs & constants from xv6-riscv (kernel/fs.h, kernel/stat.h)
# Disk layout: [ boot | superblock | log | inodes | bitmap | data ]

import struct

ROOTINO = 1
BSIZE = 1024
FSMAGIC = 0x10203040

NDIRECT = 12
NINDIRECT = BSIZE // 4        # 256 block addrs in one indirect block
MAXFILE = NDIRECT + NINDIRECT # 268 blocks max (~268 KB)

DIRSIZ = 14

# File types (kernel/stat.h)
T_UNUSED = 0
T_DIR = 1
T_FILE = 2
T_DEVICE = 3

DINODE_SIZE = 64
IPB = BSIZE // DINODE_SIZE    # 16 inodes per block
BPB = BSIZE * 8               # 8192 bits per bitmap block

# Little-endian, packed (no struct padding on disk)
SUPERBLOCK_FORMAT = "<8I"     # magic, size, nblocks, ninodes, nlog, logstart, inodestart, bmapstart
SUPERBLOCK_SIZE = struct.calcsize(SUPERBLOCK_FORMAT)

DINODE_FORMAT = "<hhhhI" + f"{NDIRECT + 1}I"
assert struct.calcsize(DINODE_FORMAT) == DINODE_SIZE

DIRENT_FORMAT = f"<H{DIRSIZ}s"
DIRENT_SIZE = struct.calcsize(DIRENT_FORMAT)
assert DIRENT_SIZE == 16


class Superblock:
    def __init__(self, magic, size, nblocks, ninodes, nlog, logstart, inodestart, bmapstart):
        self.magic = magic
        self.size = size
        self.nblocks = nblocks
        self.ninodes = ninodes
        self.nlog = nlog
        self.logstart = logstart
        self.inodestart = inodestart
        self.bmapstart = bmapstart

    @classmethod
    def unpack(cls, data):
        fields = struct.unpack_from(SUPERBLOCK_FORMAT, data, 0)
        return cls(*fields)

    def pack(self):
        return struct.pack(
            SUPERBLOCK_FORMAT,
            self.magic, self.size, self.nblocks, self.ninodes,
            self.nlog, self.logstart, self.inodestart, self.bmapstart
        )


class Dinode:
    def __init__(self, type=T_UNUSED, major=0, minor=0, nlink=0, size=0, addrs=None):
        self.type = type
        self.major = major
        self.minor = minor
        self.nlink = nlink
        self.size = size
        self.addrs = list(addrs) if addrs is not None else [0] * (NDIRECT + 1)

    @classmethod
    def unpack(cls, data):
        v = struct.unpack(DINODE_FORMAT, data)
        return cls(v[0], v[1], v[2], v[3], v[4], list(v[5:]))

    def pack(self):
        return struct.pack(
            DINODE_FORMAT,
            self.type, self.major, self.minor, self.nlink, self.size,
            *self.addrs
        )


class Dirent:
    def __init__(self, inum, name):
        self.inum = inum
        self.name = name

    @classmethod
    def unpack(cls, data):
        inum, raw = struct.unpack(DIRENT_FORMAT, data)
        # Note to self: 14-char names don't have a '\0' terminator in xv6
        end = raw.find(b'\x00')
        if end != -1:
            raw = raw[:end]
        return cls(inum, raw.decode('latin1', errors='replace'))

    def pack(self):
        name_bytes = self.name.encode('latin1', errors='replace')[:DIRSIZ]
        return struct.pack(DIRENT_FORMAT, self.inum, name_bytes.ljust(DIRSIZ, b'\x00'))


def IBLOCK(inum, sb):
    return (inum // IPB) + sb.inodestart


def BBLOCK(b, sb):
    return (b // BPB) + sb.bmapstart
