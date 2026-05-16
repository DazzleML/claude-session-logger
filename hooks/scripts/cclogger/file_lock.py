"""Cross-platform file locking primitives.

Wraps msvcrt.locking (Windows) / fcntl.flock (POSIX) so the rest of
the codebase doesn't see platform branches. Used by file_io.atomic_append
to coordinate appends across hook subprocess invocations.

Both backends use cooperative locking on byte 0 of the file. Other
processes following the same protocol are excluded; processes that
ignore the protocol (e.g., a text editor reading the file) are not
blocked, which is exactly the desired behavior for a write-ahead log
opened simultaneously by hook writers and by user-side readers.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import msvcrt

    def lock_exclusive(fp) -> None:
        """Acquire exclusive lock on `fp` (blocking).

        Locks 1 byte at file position 0 via msvcrt.locking with LK_LOCK.
        Save/restore the original position so append semantics are
        preserved for the caller.

        Raises OSError on failure.
        """
        pos = fp.tell()
        fp.seek(0)
        try:
            msvcrt.locking(fp.fileno(), msvcrt.LK_LOCK, 1)
        finally:
            fp.seek(pos)

    def lock_nonblocking(fp) -> bool:
        """Try to acquire exclusive lock without blocking.

        Returns True on success, False if the file is already locked
        by another process. Never raises on lock contention.
        """
        pos = fp.tell()
        fp.seek(0)
        try:
            try:
                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        finally:
            fp.seek(pos)

    def unlock(fp) -> None:
        """Release the lock acquired via lock_exclusive / lock_nonblocking."""
        pos = fp.tell()
        fp.seek(0)
        try:
            try:
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass  # Lock already released or never held
        finally:
            fp.seek(pos)

else:
    import fcntl

    def lock_exclusive(fp) -> None:
        """Acquire exclusive lock on `fp` (blocking) via fcntl.flock."""
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)

    def lock_nonblocking(fp) -> bool:
        """Try to acquire exclusive lock without blocking.

        Returns True on success, False if the file is already locked.
        """
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, IOError):
            return False

    def unlock(fp) -> None:
        """Release the lock acquired via lock_exclusive / lock_nonblocking."""
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
