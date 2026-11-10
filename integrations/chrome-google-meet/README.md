# Google Meet auto start on macOS + Chrome

This companion extension requests local Meaty recording after a visible joined-call control appears on a Google Meet meeting page. It does not capture audio itself, send a meeting bot, or send meeting data to a network service. Meaty uses its normal recording flow, selected devices, model checks, and recording indicator.

## Current status

- Implemented on branch `feat/meeting-autostart` against upstream commit `07c4dfd`.
- 16 extension tests and 6 native-host tests pass; frontend TypeScript check passes.
- Full macOS release build succeeds with Xcode installed; the app bundle passes `codesign --verify --deep --strict`. Google Meet auto-start was verified live. Auto-stop requires both the updated app and extension 0.2.0.
- The automation browser policy blocks `chrome://extensions`; the user must load the unpacked extension there manually.
- Teams web and Zoom web detectors are not included in this first milestone.
- Version 0.2.0 stops companion-started recordings after leaving/ending the call or closing its tab, following an eight-second reconnect grace period. With multiple joined tabs, the last one must end. Manually started recordings are left alone.
- Chrome's extension switch disables future automatic starts; it does not stop an existing recording.

## Architecture

The native-host name and bridge directory below are compatibility identifiers retained by Meaty.

`content.js` detects a visible leave-call control (including the `call_end` icon for localized UI) on Google Meet meeting URLs. Pre-join camera/mic previews are ignored. A call session ID survives page reloads and rotates after the joined-call interface has been absent for more than five seconds.

`background.js` checks the extension's enabled setting and deduplicates accepted call sessions. It uses Chrome native messaging with the host `ai.meetily.meeting_autostart`. The native host manifest permits only the extension ID derived from the committed manifest key.

`native-host.py` validates and frames messages, starts the explicitly configured custom app if needed (the legacy fallback is `/Applications/meetily.app`; configure `/Applications/MEATY.app` for Meaty), and sends a request over the app's private Unix socket. The socket is mode 0600 and has no TCP port. Native host responses acknowledge the queued request, not successful audio recording. Missing models or denied permissions are displayed by Meaty's existing recording UI.

The Rust bridge tracks joined call sessions and queues start/stop actions. End notifications cancel pending starts; stopping waits eight seconds after the last active call ends. A reconnect cancels that stop. The frontend marks ownership only after a companion start succeeds and clears it on the recording-stopped event, then routes automatic stops through the normal Stop button save flow. The mounted frontend consumes requests and uses the existing sidebar recording flow. A manually stopped recording stays stopped for that accepted call session while the app/extension session remains alive. Restarting the app/browser or disabling/re-enabling/reloading the extension can reset this suppression.

## Build prerequisites

Use full Xcode, its macOS SDK, Rust, CMake, Node.js, and pnpm 9.15.9. Open Xcode once and complete its setup. Select the Xcode developer directory if Command Line Tools is still selected:

```sh
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
```

Follow the repository's `docs/BUILDING.md`, and install JS dependencies using the committed pnpm version:

```sh
cd frontend
npx --yes pnpm@9.15.9 install --frozen-lockfile
```

On the development Mac, the `llama-cpp-sys-2` dependency selected incompatible OpenSSL 4 headers. Building its CMake project against installed OpenSSL 3.6 resolved that error. The resulting source-built helper is at `target/release/llama-helper`; copy it to `frontend/src-tauri/binaries/llama-helper-aarch64-apple-darwin` before bundling. FFmpeg is an unchanged upstream sidecar.

The custom build disables official updater endpoints and updater artifact signing so an upstream update does not overwrite the integration. Future upstream updates should be merged into the source branch and rebuilt.

## Install after the app build succeeds

1. Quit the installed Meaty app. Preserve `~/Library/Application Support/com.meetily.ai`, which contains recordings, models, and settings. Install the newly built `MEATY.app` at `/Applications/MEATY.app`.
2. Install the native host for your account:

   ```sh
   /usr/bin/python3 integrations/chrome-google-meet/install-host.py --app /Applications/MEATY.app
   ```

3. In Chrome, open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select this directory. Keep the directory in place. The extension's fixed ID is in `extension-id.txt`.
4. Open the extension popup. The **Record when I join Google Meet** switch defaults to enabled. Reload any Google Meet tabs that were already open before installation.
5. Join a test call and check Meaty's recording indicator. macOS may require renewed microphone and system-audio permissions for the custom build.
6. Leave the call or close its tab. After about eight seconds, verify Meaty stops and saves through its normal workflow. Manual stopping remains available.

## Validation

```sh
node --test integrations/chrome-google-meet/test-extension.cjs
python3 integrations/chrome-google-meet/test-native-host.py
cd frontend
npx --yes pnpm@9.15.9 exec tsc --noEmit
```

Live acceptance checks: pre-join does not start recording; joining starts exactly one recording; muting does not restart/stop it; leaving/ending or closing the last call tab stops and saves; a brief reconnect does not stop; a manually started recording is not stopped by a meeting end; manually stopping does not restart it on heartbeat or page reload; leaving and rejoining starts a new recording when idle; disabled extension does not launch/start Meaty; app closed at join launches it; missing model and denied audio permissions display actionable errors.

Google can change its meeting UI. If detection stops working, update the content detector and verify against a live test meeting.

## Uninstall companion

Remove the extension in Chrome. Remove the native host manifest at `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/ai.meetily.meeting_autostart.json` and the `~/Library/Application Support/MeetilyMeetingBridge` directory. Your Meaty recordings and settings are separate and should be retained.

To select a custom app outside Applications, run `python3 integrations/chrome-google-meet/install-host.py --app /absolute/path/MEATY.app`. The host preserves this target in its local config file.

Version 0.1.1 also detects instant-meeting URLs under `/meet/<meeting-code>`. After updating an unpacked extension, reload it in Chrome Extensions, then reload/rejoin the Meet page. Prejoin and the post-call Rejoin screen still do not trigger recording.
