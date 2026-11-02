import importlib.util
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('host', Path(__file__).with_name('native-host.py'))
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

class NativeHostTests(unittest.TestCase):
    def input(self, message):
        data = json.dumps(message).encode()
        return patch.object(host.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(struct.pack('<I', len(data)) + data)))

    def test_socket_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix='meetily-', dir='/tmp') as temp:
            root = Path(temp)
            path = root / 'Library/Application Support/com.meetily.ai/meeting-autostart.sock'
            path.parent.mkdir(parents=True)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path)); server.listen(1); server.settimeout(3)
            received = []
            def serve():
                connection, _ = server.accept()
                with connection:
                    received.append(json.loads(connection.makefile('rb').readline()))
                    connection.sendall(b'{"accepted":true}\n')
            thread = threading.Thread(target=serve); thread.start()
            message = {'event':'joined', 'provider':'google-meet', 'session':'test-session'}
            with patch.object(host.Path, 'home', return_value=root), self.input(message):
                self.assertEqual(host.main(), {'accepted':True})
            thread.join(4); server.close()
            self.assertEqual(received, [message])

    def test_reject_oversized_frame(self):
        with patch.object(host.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(struct.pack('<I', 5000)))):
            with self.assertRaises(ValueError): host.main()

    def test_reject_wrong_provider(self):
        with self.input({'event':'joined', 'provider':'untrusted', 'session':'abc'}):
            with self.assertRaises(ValueError): host.main()

    def test_reject_truncated_frame(self):
        with patch.object(host.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'\x01'))):
            with self.assertRaises(EOFError): host.main()

if __name__ == '__main__': unittest.main()
