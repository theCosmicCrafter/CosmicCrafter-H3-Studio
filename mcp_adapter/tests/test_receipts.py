import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from h3c_mcp.transport import StudioError
try:
    from h3c_mcp.receipts import ReceiptStore
except ImportError:
    ReceiptStore = None


class ReceiptTest(unittest.TestCase):
    def test_os_lock_is_nonblocking_and_released_after_process_exit(self):
        self.assertIsNotNone(ReceiptStore, 'Use durable OS-released receipt locks')
        with tempfile.TemporaryDirectory() as directory:
            script = "from h3c_mcp.receipts import ReceiptStore; import sys,os; s=ReceiptStore(sys.argv[1],'host'); c=s.claim('key','a'*64); c.__enter__(); s.write('key',dict(request_sha256='a'*64,state='submitting')); print('locked',flush=True); sys.stdin.readline(); os._exit(0)"
            child = subprocess.Popen([sys.executable, '-c', script, directory], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                store = ReceiptStore(Path(directory), 'host')
                with self.assertRaisesRegex(StudioError, 'busy'):
                    with store.claim('key', 'a'*64):
                        pass
                child.communicate('release\n', timeout=10)
                with store.claim('key', 'a'*64) as record:
                    self.assertEqual(record['state'], 'submitting')
                with self.assertRaisesRegex(StudioError, 'key'):
                    with store.claim('key', 'b'*64):
                        pass
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate()
