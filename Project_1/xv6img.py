# Low-level access layer for xv6 fs.img (block I/O, dinodes, readi, path lookup).
# Mirrors kernel/fs.c, skipping the WAL/buffer cache since nothing else writes while mounted.

import errno
from xv6defs import (
    BSIZE, BPB, FSMAGIC, ROOTINO, T_DIR,
    DIRENT_SIZE, IPB, NDIRECT, DINODE_SIZE,
    Superblock, Dinode, Dirent, IBLOCK
)
import alloc


class XV6Image:
    def __init__(self, filepath, mode="r+b"):
        self.filepath = filepath
        self.f = open(filepath, mode)
        self.sb = self._read_superblock()

    def close(self):
        if self.f and not self.f.closed:
            self.f.flush()
            self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _read_superblock(self):
        blk = self.read_block(1)  # block 0 is boot sector, superblock sits at block 1
        sb = Superblock.unpack(blk[:32])
        if sb.magic != FSMAGIC:
            raise ValueError(f"Bad superblock magic: 0x{sb.magic:x} (expected 0x{FSMAGIC:x})")
        return sb

    def read_block(self, b):
        self.f.seek(b * BSIZE)
        data = self.f.read(BSIZE)
        if len(data) < BSIZE:
            raise IOError(f"Short read on block {b}: got {len(data)} bytes")
        return data

    def write_block(self, b, data):
        if len(data) != BSIZE:
            raise ValueError(f"Expected {BSIZE}-byte block, got {len(data)}")
        self.f.seek(b * BSIZE)
        self.f.write(data)

    def read_dinode(self, inum):
        if inum < 1 or inum >= self.sb.ninodes:
            raise ValueError(f"Inode {inum} out of range")
        blk = self.read_block(IBLOCK(inum, self.sb))
        off = (inum % IPB) * DINODE_SIZE
        return Dinode.unpack(blk[off:off + DINODE_SIZE])

    def write_dinode(self, inum, dinode):
        if inum < 1 or inum >= self.sb.ninodes:
            raise ValueError(f"Inode {inum} out of range")
        bnum = IBLOCK(inum, self.sb)
        off = (inum % IPB) * DINODE_SIZE
        buf = bytearray(self.read_block(bnum))
        buf[off:off + DINODE_SIZE] = dinode.pack()
        self.write_block(bnum, bytes(buf))

    # Port of kernel/fs.c: readi()
    def readi(self, inum, offset, n):
        if offset < 0:
            raise ValueError("Negative offset")

        ip = self.read_dinode(inum)
        if offset >= ip.size or n <= 0:
            return b""

        if offset + n > ip.size:
            n = ip.size - offset

        out = bytearray()
        tot = 0
        while tot < n:
            pos = offset + tot
            bn = pos // BSIZE
            boff = pos % BSIZE
            m = min(n - tot, BSIZE - boff)

            addr = alloc.bmap(self, ip, inum, bn, alloc=False)
            if addr == 0:
                # Sparse/unallocated block reads back as zeroes
                out.extend(b'\x00' * m)
            else:
                blk = self.read_block(addr)
                out.extend(blk[boff:boff + m])

            tot += m

        return bytes(out)

    def dirlookup(self, dp_inum, name):
        dp = self.read_dinode(dp_inum)
        if dp.type != T_DIR:
            raise OSError(errno.ENOTDIR, f"Inode {dp_inum} is not a directory")

        off = 0
        while off < dp.size:
            raw = self.readi(dp_inum, off, DIRENT_SIZE)
            if len(raw) < DIRENT_SIZE:
                break
            de = Dirent.unpack(raw)
            if de.inum != 0 and de.name == name:
                return (de.inum, off)
            off += DIRENT_SIZE

        return None

    def get_dirents(self, dp_inum):
        dp = self.read_dinode(dp_inum)
        if dp.type != T_DIR:
            raise OSError(errno.ENOTDIR, f"Inode {dp_inum} is not a directory")

        entries = []
        off = 0
        while off < dp.size:
            raw = self.readi(dp_inum, off, DIRENT_SIZE)
            if len(raw) < DIRENT_SIZE:
                break
            de = Dirent.unpack(raw)
            if de.inum != 0:
                entries.append((de.inum, de.name))
            off += DIRENT_SIZE

        return entries

    def namei(self, path):
        parts = [p for p in path.strip('/').split('/') if p]
        cur = ROOTINO
        for p in parts:
            hit = self.dirlookup(cur, p)
            if hit is None:
                return None
            cur = hit[0]
        return cur

    def nameiparent(self, path):
        parts = [p for p in path.strip('/').split('/') if p]
        if not parts:
            return (None, "")

        name = parts[-1]
        cur = ROOTINO
        for p in parts[:-1]:
            hit = self.dirlookup(cur, p)
            if hit is None:
                return (None, name)
            cur = hit[0]

        return (cur, name)


# Builds a blank fs.img (mostly for unit tests, modeled on mkfs/mkfs.c)
def create_empty_image(filepath, nblocks=2000, ninodes=200, nlog=30):
    logstart = 2
    inodestart = 2 + nlog
    ninodeblocks = (ninodes + IPB - 1) // IPB
    bmapstart = inodestart + ninodeblocks
    nbmapblocks = (nblocks + BPB - 1) // BPB
    datastart = bmapstart + nbmapblocks

    sb = Superblock(
        magic=FSMAGIC,
        size=nblocks,
        nblocks=nblocks - datastart,
        ninodes=ninodes,
        nlog=nlog,
        logstart=logstart,
        inodestart=inodestart,
        bmapstart=bmapstart
    )

    with open(filepath, "wb") as f:
        zero = b'\x00' * BSIZE
        for _ in range(nblocks):
            f.write(zero)

        f.seek(1 * BSIZE)
        f.write(sb.pack())

        # Mark metadata blocks + root dir data block as used in bitmap
        bmap = bytearray(nbmapblocks * BSIZE)
        for b in range(datastart + 1):
            bmap[b // 8] |= (1 << (b % 8))

        f.seek(bmapstart * BSIZE)
        f.write(bmap)

        # Root dir (inode 1): xv6 sets nlink=1 for root, '.' isn't counted
        root_blk = datastart
        root_ip = Dinode(
            type=T_DIR,
            nlink=1,
            size=2 * DIRENT_SIZE,
            addrs=[root_blk] + [0] * NDIRECT
        )
        f.seek(IBLOCK(ROOTINO, sb) * BSIZE + (ROOTINO % IPB) * DINODE_SIZE)
        f.write(root_ip.pack())

        dot = Dirent(ROOTINO, ".").pack()
        dotdot = Dirent(ROOTINO, "..").pack()
        blk_data = dot + dotdot + b'\x00' * (BSIZE - 2 * DIRENT_SIZE)
        f.seek(root_blk * BSIZE)
        f.write(blk_data)
