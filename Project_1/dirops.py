# Directory & namespace ops for xv6 (dirlink, create, mkdir, unlink, link).
# Ported from kernel/fs.c and kernel/sysfile.c.

import errno

from xv6defs import (
    DIRSIZ, DIRENT_SIZE, T_DIR, T_FILE, T_DEVICE,
    Dirent
)
import alloc


def dirlink(img, dp_inum, name, inum):
    if not name or '/' in name or '\x00' in name:
        raise OSError(errno.EINVAL, f"Invalid entry name: {name!r}")

    encoded = name.encode('latin1', errors='replace')
    if len(encoded) > DIRSIZ:
        raise OSError(errno.ENAMETOOLONG, f"File name exceeds DIRSIZ ({DIRSIZ}): {name}")

    dp = img.read_dinode(dp_inum)
    if dp.type != T_DIR:
        raise OSError(errno.ENOTDIR, f"Inode {dp_inum} is not a directory")

    # scan for duplicates and grab the first free slot (inum == 0) if there is one
    free_off = None
    off = 0
    while off < dp.size:
        data = img.readi(dp_inum, off, DIRENT_SIZE)
        if len(data) < DIRENT_SIZE:
            break
        de = Dirent.unpack(data)
        if de.inum != 0:
            if de.name == name:
                raise OSError(errno.EEXIST, f"Entry '{name}' already exists in directory {dp_inum}")
        elif free_off is None:
            free_off = off
        off += DIRENT_SIZE

    target_off = free_off if free_off is not None else dp.size
    de = Dirent(inum, name)
    alloc.writei(img, dp_inum, de.pack(), target_off)
    return 0


def isdirempty(img, inum):
    dp = img.read_dinode(inum)
    if dp.type != T_DIR:
        raise OSError(errno.ENOTDIR, f"Inode {inum} is not a directory")

    off = 0
    while off < dp.size:
        data = img.readi(inum, off, DIRENT_SIZE)
        if len(data) < DIRENT_SIZE:
            break
        de = Dirent.unpack(data)
        if de.inum != 0 and de.name not in ('.', '..'):
            return False
        off += DIRENT_SIZE

    return True


def create(img, path, type_=T_FILE, major=0, minor=0):
    """Create a file/dir at path and return its inum (or existing file inum if type_==T_FILE)."""
    dp_inum, name = img.nameiparent(path)
    if dp_inum is None:
        raise OSError(errno.ENOENT, f"Parent directory does not exist for: {path}")

    if not name or name in ('.', '..'):
        raise OSError(errno.EINVAL, f"Cannot create with name: {name!r}")

    encoded = name.encode('latin1', errors='replace')
    if len(encoded) > DIRSIZ:
        raise OSError(errno.ENAMETOOLONG, f"File name exceeds DIRSIZ ({DIRSIZ}): {name}")

    # xv6 open(..., O_CREATE) returns the existing inode for regular files
    found = img.dirlookup(dp_inum, name)
    if found is not None:
        existing_inum, _ = found
        existing_ip = img.read_dinode(existing_inum)
        if type_ == T_FILE and existing_ip.type in (T_FILE, T_DEVICE):
            return existing_inum
        raise OSError(errno.EEXIST, f"File or directory already exists: {path}")

    ip_inum = alloc.ialloc(img, type_)

    try:
        ip = img.read_dinode(ip_inum)
        ip.type = type_
        ip.major = major
        ip.minor = minor
        ip.nlink = 1
        ip.size = 0
        img.write_dinode(ip_inum, ip)

        if type_ == T_DIR:
            # '.' does not bump nlink in xv6 (avoids cycle ref counts)
            dirlink(img, ip_inum, ".", ip_inum)
            dirlink(img, ip_inum, "..", dp_inum)

        dirlink(img, dp_inum, name, ip_inum)

        if type_ == T_DIR:
            # child's '..' points to dp, so bump parent nlink
            dp = img.read_dinode(dp_inum)
            dp.nlink += 1
            img.write_dinode(dp_inum, dp)

        return ip_inum

    except Exception:
        # clean up inode/blocks if linking failed halfway
        alloc.itrunc(img, ip_inum)
        alloc.ifree(img, ip_inum)
        raise


def mkdir(img, path):
    return create(img, path, type_=T_DIR, major=0, minor=0)


def unlink(img, path):
    dp_inum, name = img.nameiparent(path)
    if dp_inum is None:
        raise OSError(errno.ENOENT, f"Parent directory does not exist for: {path}")

    if name in ('.', '..'):
        raise OSError(errno.EINVAL, "Cannot unlink '.' or '..'")

    found = img.dirlookup(dp_inum, name)
    if found is None:
        raise OSError(errno.ENOENT, f"No such file or directory: {path}")

    ip_inum, off = found
    ip = img.read_dinode(ip_inum)

    if ip.nlink < 1:
        raise RuntimeError(f"Corrupt filesystem: inode {ip_inum} has nlink < 1 ({ip.nlink})")

    if ip.type == T_DIR:
        if not isdirempty(img, ip_inum):
            raise OSError(errno.ENOTEMPTY, f"Directory not empty: {path}")

    # zero out the dirent slot in parent
    alloc.writei(img, dp_inum, b'\x00' * DIRENT_SIZE, off)

    # drop parent's nlink since child's '..' is gone
    if ip.type == T_DIR:
        dp = img.read_dinode(dp_inum)
        dp.nlink -= 1
        img.write_dinode(dp_inum, dp)

    ip.nlink -= 1

    if ip.nlink == 0:
        alloc.itrunc(img, ip_inum)
        alloc.ifree(img, ip_inum)
    else:
        img.write_dinode(ip_inum, ip)

    return 0


def link(img, oldpath, newpath):
    """Create hard link newpath -> oldpath (files only, no dirs)."""
    ip_inum = img.namei(oldpath)
    if ip_inum is None:
        raise OSError(errno.ENOENT, f"Source path does not exist: {oldpath}")

    ip = img.read_dinode(ip_inum)
    if ip.type == T_DIR:
        raise OSError(errno.EPERM, f"Cannot hard link directories: {oldpath}")

    dp_inum, name = img.nameiparent(newpath)
    if dp_inum is None:
        raise OSError(errno.ENOENT, f"Destination parent directory does not exist: {newpath}")

    ip.nlink += 1
    img.write_dinode(ip_inum, ip)

    try:
        dirlink(img, dp_inum, name, ip_inum)
    except Exception:
        ip.nlink -= 1
        img.write_dinode(ip_inum, ip)
        raise

    return 0
