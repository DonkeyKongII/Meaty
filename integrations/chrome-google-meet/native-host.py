#!/usr/bin/python3
"""Chrome native messaging host. No network listener or meeting audio access.

Speaks the native-messaging protocol in a loop: the extension keeps one
persistent port (connectNative) for the whole browser session, so this process
is spawned once instead of ~1,800 times per hour of meeting. One-shot
sendNativeMessage clients still work: Chrome closes stdin after the message,
the read loop sees EOF and exits.
"""
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

def handle(message):
    if message.get('event') not in ('joined', 'ended', 'participants') or message.get('provider') != 'google-meet':
        raise ValueError('Unsupported event')
    count = message.get('participant_count')
    if count is not None and (type(count) is not int or not 1 <= count <= 100): raise ValueError('Invalid participant count')
    people = message.get('participants', [])
    if not isinstance(people, list) or len(people)>100 or any(not isinstance(p,dict) or not isinstance(p.get('name'),str) or not 1<=len(p['name'])<=100 for p in people):
        raise ValueError('Invalid participants')
    for field,limit in [('meet_title',500),('meet_url',200)]:
        if field in message and (not isinstance(message[field],str) or len(message[field])>limit): raise ValueError('Invalid '+field)
    session = message.get('session')
    if not isinstance(session, str) or not 1 <= len(session) <= 128: raise ValueError('Invalid session')
    path = str(Path.home() / 'Library/Application Support/com.meetily.ai/meeting-autostart.sock')
    result = None
    for attempt in range(60):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(3)
                connection.connect(path)
                connection.sendall(json.dumps(message, ensure_ascii=False).encode() + b'\n')
                result = json.loads(connection.makefile('rb').readline(4096))
                break
        except (OSError, ValueError):
            # A heartbeat proves the call is still live after an app crash.
            # Recover immediately instead of waiting for a second poll/join.
            if message['event'] == 'ended':
                return {'accepted':False, 'error':'Meetily is not running'}
            if attempt == 0:
                subprocess.run(['/usr/bin/open', '-g', app_path()], check=True, stdout=subprocess.DEVNULL)
            time.sleep(0.5)
    return result or {'accepted':False, 'error':'Meetily bridge did not become ready'}

def main():
    while True:
        header = sys.stdin.buffer.read(4)
        if not header:
            return  # Port closed (or one-shot client finished): exit.
        if len(header) < 4: raise EOFError('Incomplete native message')
        length = struct.unpack('<I', header)[0]
        if length > 65536: raise ValueError('Message too large')
        message = json.loads(exact_read(length))
        try:
            response = handle(message)
        except Exception as error:
            response = {'accepted':False, 'error':str(error)}
        payload = json.dumps(response).encode()
        sys.stdout.buffer.write(struct.pack('<I', len(payload)) + payload)
        sys.stdout.buffer.flush()

if __name__ == '__main__':
    try: main()
    except Exception as error:
        payload = json.dumps({'accepted':False, 'error':str(error)}).encode()
        sys.stdout.buffer.write(struct.pack('<I', len(payload)) + payload)
        sys.stdout.buffer.flush()
