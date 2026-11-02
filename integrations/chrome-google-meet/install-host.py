#!/usr/bin/python3
"""Install the companion host for the current macOS Chrome user."""
import argparse, json, shutil
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--app', type=Path, help='Absolute path to the custom Meetily .app')
args = parser.parse_args()
if args.app and (not args.app.is_absolute() or args.app.suffix != '.app' or not args.app.is_dir()):
    parser.error('--app must name an existing absolute .app directory')
source = Path(__file__).resolve().parent
root = Path.home() / 'Library/Application Support/MeetilyMeetingBridge'
root.mkdir(parents=True, exist_ok=True)
if args.app:
    (root / 'config.json').write_text(json.dumps({'app_path':str(args.app)}))
host = root / 'native-host.py'
shutil.copy2(source / 'native-host.py', host)
host.chmod(0o700)
extension_id = (source / 'extension-id.txt').read_text().strip()
manifest = {'name':'ai.meetily.meeting_autostart','description':'Meetily Google Meet bridge','path':str(host),'type':'stdio','allowed_origins':[f'chrome-extension://{extension_id}/']}
destination = Path.home() / 'Library/Application Support/Google/Chrome/NativeMessagingHosts'
destination.mkdir(parents=True, exist_ok=True)
(destination / 'ai.meetily.meeting_autostart.json').write_text(json.dumps(manifest, indent=2))
print('Installed native host for extension ' + extension_id)
