"""Atomic local receipts with process-lifetime, nonblocking ownership locks."""
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .transport import StudioError, encoded, parse


class ReceiptStore:
    def __init__(self, state_dir, studio_identity):
        self.root = Path(state_dir) / hashlib.sha256(studio_identity.encode()).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key, suffix='.json'):
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            raise StudioError('Use a nonempty request key of at most 256 characters.', code='invalid_request_key')
        return self.root / (hashlib.sha256(key.encode()).hexdigest() + suffix)

    def load(self, key):
        try:
            return parse(self._path(key).read_bytes())
        except FileNotFoundError:
            return None

    def write(self, key, value):
        path = self._path(key)
        fd, temporary = tempfile.mkstemp(dir=self.root, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded(value))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def claim(self, key, request_hash):
        with self._path(key, '.lock').open('a+b') as lock:
            lock.seek(0)
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise StudioError('Request receipt is busy in another process.', code='receipt_busy') from error
            try:
                value = self.load(key)
                if value is not None and value.get('request_sha256') != request_hash:
                    raise StudioError('Request key already belongs to different content.', code='idempotency_conflict')
                yield value
            finally:
                lock.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
