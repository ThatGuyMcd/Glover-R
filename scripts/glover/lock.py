"""Non-blocking process lock; the OS releases the lock after a crash."""
from __future__ import annotations
from contextlib import contextmanager
import os
from pathlib import Path

@contextmanager
def build_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('Build lock must not be a symlink.')
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        locked = False
        try:
            if os.name == 'nt':
                import msvcrt
                try: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error: raise RuntimeError('Another Glover-R build is already running.') from error
            else:
                import fcntl
                try: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error: raise RuntimeError('Another Glover-R build is already running.') from error
            locked = True
            yield
        finally:
            if locked:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
