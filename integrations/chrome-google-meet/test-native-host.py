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
    def run_host(self, *messages):
        """Feed messages through the persistent-port loop; return the responses."""
        data = b''.join(
            struct.pack('<I', len(json.dumps(m).encode())) + json.dumps(m).encode()
            for m in messages
        )
        out = io.BytesIO()
        with patch.object(host.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(data))), \
             patch.object(host.sys, 'stdout', SimpleNamespace(buffer=out)):
            host.main()
        out.seek(0)
        responses = []
        while True:
            header = out.read(4)
            if not header: break
            responses.append(json.loads(out.read(struct.unpack('<I', header)[0])))
        return responses

    def test_socket_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix='meetily-', dir='/tmp') as temp:
            root = Path(temp)
            path = root / 'Library/Application Support/com.meetily.ai/meeting-autostart.sock'
            path.parent.mkdir(parents=True)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path)); server.listen(2); server.settimeout(3)
            received = []
            def serve():
                for _ in range(2):
                    connection, _ = server.accept()
                    with connection:
                        received.append(json.loads(connection.makefile('rb').readline()))
                        connection.sendall(b'{"accepted":true}\n')
            thread = threading.Thread(target=serve); thread.start()
            first = {'event':'joined', 'provider':'google-meet', 'session':'test-session'}
            second = {'event':'ended', 'provider':'google-meet', 'session':'test-session'}
            with patch.object(host.Path, 'home', return_value=root):
                responses = self.run_host(first, second)
            thread.join(4); server.close()
            # One host process handled both messages (persistent port behavior).
            self.assertEqual(responses, [{'accepted':True}, {'accepted':True}])
            self.assertEqual(received, [first, second])

    def test_end_does_not_launch_closed_app(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(host.Path, 'home', return_value=Path(temp)), patch.object(host.subprocess, 'run') as launch:
            responses = self.run_host({'event':'ended','provider':'google-meet','session':'old'})
            self.assertFalse(responses[0]['accepted'])
            launch.assert_not_called()

    def test_configured_custom_app_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / 'custom/meetily.app'
            app.mkdir(parents=True)
            config = root / 'Library/Application Support/MeetilyMeetingBridge/config.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'app_path':str(app)}))
            with patch.object(host.Path, 'home', return_value=root):
                self.assertEqual(host.app_path(), str(app))
            config.write_text(json.dumps({'app_path':'relative.app'}))
            with patch.object(host.Path, 'home', return_value=root):
                with self.assertRaises(ValueError): host.app_path()

    def test_reject_oversized_frame(self):
        with patch.object(host.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(struct.pack('<I', 5000)))):
            with self.assertRaises(ValueError): host.main()

    def test_reject_wrong_provider(self):
        # Per-message errors are reported in the response so one bad message
        # cannot kill the persistent host process.
        responses = self.run_host({'event':'joined', 'provider':'untrusted', 'session':'abc'})
        self.assertEqual(responses[0]['accepted'], False)
        self.assertIn('Unsupported', responses[0]['error'])

    def test_reject_truncated_frame(self):
        with patch.object(host.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'\x01'))):
            with self.assertRaises(EOFError): host.main()

if __name__ == '__main__': unittest.main()
