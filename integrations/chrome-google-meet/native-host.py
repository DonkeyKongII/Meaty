#!/usr/bin/python3
"""Chrome native messaging host. No network listener or meeting audio access."""
import json, socket, struct, subprocess, sys, time
from pathlib import Path

def exact_read(count):
    chunks = bytearray()
    while len(chunks) < count:
        chunk = sys.stdin.buffer.read(count - len(chunks))
        if not chunk: raise EOFError("Incomplete native message")
        chunks.extend(chunk)
    return bytes(chunks)

def app_path():
    config = Path.home() / 'Library/Application Support/MeetilyMeetingBridge/config.json'
    if config.is_file():
        target = Path(json.loads(config.read_text())['app_path'])
        if not target.is_absolute() or target.suffix != '.app' or not target.is_dir():
            raise ValueError('Configured Meetily app does not exist')
        return str(target)
    return '/Applications/meetily.app'

def main():
    length = struct.unpack('<I', exact_read(4))[0]
    if length > 4096: raise ValueError('Message too large')
    message = json.loads(exact_read(length))
    if message.get('event') not in ('joined', 'ended') or message.get('provider') != 'google-meet':
        raise ValueError('Unsupported event')
    session = message.get('session')
    if not isinstance(session, str) or not 1 <= len(session) <= 128: raise ValueError('Invalid session')
    path = str(Path.home() / 'Library/Application Support/com.meetily.ai/meeting-autostart.sock')
    result = None
    for attempt in range(60):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(3)
                connection.connect(path)
                connection.sendall(json.dumps(message).encode() + b'\n')
                result = json.loads(connection.makefile('rb').readline(4096))
                break
        except (OSError, ValueError):
            if message['event'] == 'ended':
                return {'accepted':False, 'error':'Meetily is not running'}
            if attempt == 0:
                subprocess.run(['/usr/bin/open', '-g', app_path()], check=True, stdout=subprocess.DEVNULL)
            time.sleep(0.5)
    return result or {'accepted':False, 'error':'Meetily bridge did not become ready'}

if __name__ == '__main__':
    try: response = main()
    except Exception as error: response = {'accepted':False, 'error':str(error)}
    payload = json.dumps(response).encode()
    sys.stdout.buffer.write(struct.pack('<I', len(payload)) + payload)
    sys.stdout.buffer.flush()
