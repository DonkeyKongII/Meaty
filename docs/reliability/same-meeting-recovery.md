# Resume the same meeting after a process exit

Investigation: November 5, 2026. This is an implementation design; recovery is not implemented yet.

## Current failure

`RecordingSaver::initialize_meeting_folder` writes `meeting_id: None` and creates a fresh folder. `useRecordingStop` saves through `storageService.saveMeeting` only after stop and transcription drain. The companion session tracker and frontend ownership flag live in memory. After restart a heartbeat starts a new recording with no link to the old one.

Reusing the previous folder directly would be unsafe: `IncrementalAudioSaver::new` resets its checkpoint counter to zero and would reuse `audio_chunk_000.mp4`. Transcript sequence IDs also restart; the existing upsert would replace older segments with matching IDs. Recovery must address both collisions before enabling automatic continuation.

## Proposed implementation

1. Create the SQLite meeting identity at recording start, before accepting audio. Persist an atomic session manifest with meeting ID, companion provider/session token, folder, lifecycle, audio-saving preference and segment IDs. Use the persisted session token rather than only Chrome's tab number; a room URL alone must never merge different occurrences of a recurring meeting.
2. Write each recording attempt into a separate segment directory under the same meeting. Keep existing checkpoints and transcripts immutable during restart. Include the segment ID in transcript keys. Periodically commit transcript checkpoints to the existing meeting record. If audio saving is off, preserve that preference and offer transcript-only recovery.
3. On launch, inspect unfinished manifests. For companion recordings, require a fresh heartbeat for the matching session before automatic resumption. Persist manual stop and meeting end before draining so restart cannot undo an intentional stop. An old or ambiguous session gets a recover/discard choice. Bound relaunch attempts to prevent crash loops.
4. Resume into a new segment under the existing meeting ID. Store captured-audio offsets separately from wall-clock start/end and mark the unrecorded gap. Playback, transcript seeking and speaker analysis must share the captured-audio timeline. Never claim the missing interval was recorded.
5. Finalization merges segments into a temporary audio file, verifies it, then atomically replaces the final file. Upsert the existing meeting and transcript rows idempotently; queue calendar, speaker and summary work against that same ID only after capture ends. Retain source segments until finalization succeeds.
6. Add rotating local application/panic logs and record process start, recovery decision and segment transitions without transcript text. The existing native bridge can relaunch on a heartbeat; this detects process exit, not a hung audio pipeline. Add capture-progress monitoring separately with explicit retry limits.

## Required verification before installation

Crash a test recording after multiple checkpoints, resume the same live companion session, and assert one meeting ID, preserved old audio/transcript and no duplicate segments. Repeat crashes during finalization and startup. Test duplicate/out-of-order heartbeats, a different room/session, a recurring room the next day, manual stop, meeting end during an outage, browser tab restoration, microphone failure and disabled audio saving. Verify playback and transcript seeking across the gap. Do not crash a real user recording to run these tests.

## Calendar incident

The Check calendar button writes `pending` and relies on a Codex automation. Recent automation runs counted twelve pending jobs without attempting calendar lookups. The status helper now returns actionable job details, and the live automation prioritizes up to three calendar jobs before portal synchronization and requires a saved outcome or concrete failure record. A manually verified Nov 3 Softcat lookup was saved successfully, preserving the user's manual classification. UI wording is prepared in source to describe the queued state accurately; it requires an app rebuild to ship.

The next scheduled run confirmed a second failure: browser tab binding/creation fails with an internal `timeoutMs` error. Native `cua.getApp("com.google.Chrome")` accessibility controls worked for the verified lookup. Both the live automation prompt and workflow now specify this fallback. Automatic backlog completion still requires verification on a subsequent scheduled run.
