# Block & inode allocation and writei/truncate for xv6.
# Based on kernel/fs.c (balloc, bfree, ialloc, itrunc, bmap, writei).

import errno
import struct
from xv6defs import (
    BSIZE, BPB, NDIRECT, NINDIRECT, MAXFILE,
    T_UNUSED, Dinode, BBLOCK
)


def balloc(img):
    """Find a free block in the bitmap, zero it out, and return block number."""
    sb = img.sb
    for base in range(0, sb.size, BPB):
        bblock = BBLOCK(base, sb)
        buf = bytearray(img.read_block(bblock))

        limit = min(BPB, sb.size - base)
        for bi in range(limit):
            byte_idx = bi // 8
            bit_idx = bi % 8
            mask = 1 << bit_idx

            if (buf[byte_idx] & mask) == 0:
                buf[byte_idx] |= mask
                img.write_block(bblock, bytes(buf))

                blk = base + bi
                # zero out the block before handing it out
                img.write_block(blk, b'\x00' * BSIZE)
                return blk

    raise OSError(errno.ENOSPC, "No free data blocks available")


def bfree(img, b):
    sb = img.sb
    if b <= 0 or b >= sb.size:
        raise ValueError(f"Block number out of range: {b}")

    bblock = BBLOCK(b, sb)
    buf = bytearray(img.read_block(bblock))

    bi = b % BPB
    byte_idx = bi // 8
    bit_idx = bi % 8
    mask = ~(1 << bit_idx) & 0xFF

    buf[byte_idx] &= mask
    img.write_block(bblock, bytes(buf))


def ialloc(img, type_):
    sb = img.sb
    for inum in range(1, sb.ninodes):
        ip = img.read_dinode(inum)
        if ip.type == T_UNUSED:
            ip.type = type_
            ip.major = 0
            ip.minor = 0
            ip.nlink = 0
            ip.size = 0
            ip.addrs = [0] * (NDIRECT + 1)
            img.write_dinode(inum, ip)
            return inum

    raise OSError(errno.ENOSPC, "No free inodes available")


def ifree(img, inum):
    # writing an empty Dinode sets type back to T_UNUSED (0)
    img.write_dinode(inum, Dinode())


def bmap(img, inode, inum, bn, alloc=False):
    """Get disk block for logical block bn. Allocates if alloc is True."""
    if bn < 0 or bn >= MAXFILE:
        raise ValueError(f"Block number out of range: {bn}")

    # direct blocks
    if bn < NDIRECT:
        addr = inode.addrs[bn]
        if addr == 0:
            if not alloc:
                return 0
            addr = balloc(img)
            inode.addrs[bn] = addr
            img.write_dinode(inum, inode)
        return addr

    # indirect block
    bn -= NDIRECT
    if bn < NINDIRECT:
        indir = inode.addrs[NDIRECT]
        if indir == 0:
            if not alloc:
                return 0
            indir = balloc(img)
            inode.addrs[NDIRECT] = indir
            img.write_dinode(inum, inode)

        data = bytearray(img.read_block(indir))
        addr = struct.unpack_from("<I", data, bn * 4)[0]
        if addr == 0:
            if not alloc:
                return 0
            addr = balloc(img)
            struct.pack_into("<I", data, bn * 4, addr)
            img.write_block(indir, bytes(data))
        return addr

    raise ValueError(f"Block number exceeds maximum file size: {bn}")


def itrunc(img, inum):
    ip = img.read_dinode(inum)

    for i in range(NDIRECT):
        if ip.addrs[i] != 0:
            bfree(img, ip.addrs[i])
            ip.addrs[i] = 0

    indir = ip.addrs[NDIRECT]
    if indir != 0:
        indir_blk = img.read_block(indir)
        for j in range(NINDIRECT):
            addr = struct.unpack_from("<I", indir_blk, j * 4)[0]
            if addr != 0:
                bfree(img, addr)
        bfree(img, indir)
        ip.addrs[NDIRECT] = 0

    ip.size = 0
    img.write_dinode(inum, ip)


def writei(img, inum, data, offset):
    """Write data buffer into inode starting at offset."""
    if offset < 0:
        raise ValueError("Negative offset")

    total_len = len(data)
    if offset + total_len > MAXFILE * BSIZE:
        raise OSError(errno.EFBIG, "File exceeds maximum xv6 file size")

    ip = img.read_dinode(inum)
    written = 0

    while written < total_len:
        cur_off = offset + written
        bn = cur_off // BSIZE
        boff = cur_off % BSIZE
        chunk = min(total_len - written, BSIZE - boff)

        blk = bmap(img, ip, inum, bn, alloc=True)

        buf = bytearray(img.read_block(blk))
        buf[boff:boff + chunk] = data[written:written + chunk]
        img.write_block(blk, bytes(buf))

        written += chunk

    if offset + written > ip.size:
        ip.size = offset + written
        img.write_dinode(inum, ip)

    return written


def truncate(img, inum, new_size):
    """Truncate or extend file to new_size bytes."""
    if new_size < 0:
        raise ValueError("Negative size")
    if new_size > MAXFILE * BSIZE:
        raise OSError(errno.EFBIG, "File exceeds maximum xv6 file size")

    ip = img.read_dinode(inum)
    if new_size == 0:
        itrunc(img, inum)
        return

    if new_size < ip.size:
        # free blocks completely beyond new_size
        first_free = (new_size + BSIZE - 1) // BSIZE
        old_last = (ip.size + BSIZE - 1) // BSIZE

        for bn in range(first_free, old_last):
            if bn < NDIRECT:
                if ip.addrs[bn] != 0:
                    bfree(img, ip.addrs[bn])
                    ip.addrs[bn] = 0
            else:
                idx = bn - NDIRECT
                if ip.addrs[NDIRECT] != 0:
                    data = bytearray(img.read_block(ip.addrs[NDIRECT]))
                    addr = struct.unpack_from("<I", data, idx * 4)[0]
                    if addr != 0:
                        bfree(img, addr)
                        struct.pack_into("<I", data, idx * 4, 0)
                        img.write_block(ip.addrs[NDIRECT], bytes(data))

        # drop the indirect block too if nothing inside it is used anymore
        if ip.addrs[NDIRECT] != 0 and first_free <= NDIRECT:
            indir_data = img.read_block(ip.addrs[NDIRECT])
            if all(addr == 0 for addr, in struct.iter_unpack("<I", indir_data)):
                bfree(img, ip.addrs[NDIRECT])
                ip.addrs[NDIRECT] = 0

        # wipe tail bytes in the last partial block
        partial_off = new_size % BSIZE
        if partial_off != 0:
            last_bn = new_size // BSIZE
            blk = bmap(img, ip, inum, last_bn, alloc=False)
            if blk != 0:
                buf = bytearray(img.read_block(blk))
                buf[partial_off:] = b'\x00' * (BSIZE - partial_off)
                img.write_block(blk, bytes(buf))

        ip.size = new_size
        img.write_dinode(inum, ip)
    elif new_size > ip.size:
        # zero-pad if extending past EOF
        pad_len = new_size - ip.size
        zero_buf = b'\x00' * min(pad_len, BSIZE)
        curr = ip.size
        while curr < new_size:
            step = min(new_size - curr, len(zero_buf))
            writei(img, inum, zero_buf[:step], curr)
            curr += step
