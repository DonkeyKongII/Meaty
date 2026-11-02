# Persistent local speaker recognition

This feature adds post-recording diarization and explicitly enrolled voice profiles to Meetily Community Edition. It runs locally, with no inference API, meeting bot, or audio upload. It is implemented alongside Google Meet auto start on branch `feat/meeting-autostart`.

## Use

1. Open a saved meeting's Transcript tab and expand **Speakers**.
2. Choose **Detect speakers**. Leave the count blank for automatic clustering, or provide a known count (1–20).
3. Listen to each sample and enter a name. **Save speaker** names the group for that meeting.
4. Check **Remember this voice in future meetings** to explicitly enroll a reusable profile. At least eight seconds of clear speech and a consistent voice group are required. Choose an existing person from the dropdown to explicitly replace that person's reference with the current voice.
5. After a profile exists, opening a new, unanalyzed saved meeting automatically identifies speakers. Disable this behavior with the checkbox in the Speakers panel. It waits while Meetily is recording and will attempt each meeting only once per view session; manual retry remains available.
6. Rename or delete saved profiles in **Saved voice profiles**. Deleting removes the reference vector and linked per-meeting enrollment vectors, while preserving historical labels, meeting recordings, and playback samples.

Names appear above timestamped transcript chunks. Chunks containing material portions of multiple speaker turns display multiple names. Legacy transcript rows without recording-relative timestamps are left unlabeled. These annotations do not yet change summary generation or transcript-copy/export output.

## Recognition behavior

- Local segmentation: sherpa-onnx's Pyannote segmentation 3.0 ONNX model.
- Local embedding: 3D-Speaker CAMPPlus Chinese/English common advanced ONNX model.
- A persistent local SQLite database stores model-versioned vectors, profile names, meeting analyses, and explicit corrections. Profiles survive application restarts and source rebuilds with the same app identity.
- Similarity is cosine similarity, not a calibrated probability. The initial match threshold is 0.65 with a 0.10 margin over the next person. Matching requires five seconds of usable material; enrollment requires eight.
- Overlapping speech is excluded from embedding material. Substantial disagreement between segment embeddings blocks enrollment and automatic naming for that group. This is a heuristic, not a guarantee of a clean or correct cluster.
- Automatic guesses never update voice profiles. Only an explicit enrollment updates a person's reference. An update currently replaces the reference; it does not maintain a multi-session voice gallery.
- Low scores, ambiguous matches, short speech, or inconsistent groups stay unnamed. There are still possible false matches and diarization errors. Listen before enrollment and correct mistakes; changed microphones, noise, overlap, and voice changes can affect results. Thresholds need validation on real meetings.
- Re-detecting replaces the current meeting's speaker assignments, while retaining the saved voice library.
- Model IDs prevent reusing incompatible embeddings after changing the model. New model versions require re-enrollment.

## Installation and storage

Run this once from the source checkout with Python 3.9 on macOS:

```sh
python3 integrations/speakers/setup.py
```

The installer creates an isolated Python environment and downloads hash-verified models under:

`~/Library/Application Support/com.meetily.ai/speaker-recognition/`

Profiles and meeting results are stored in `voices.sqlite` (mode 0600) inside the private runtime directory (mode 0700). Playback samples are local WAV files. Keep this directory in backups if you want profiles to survive deletion of the app's data. This initial implementation is local for one Mac; no profile sync or dedicated profile export is included.

The application bundles `speaker_runtime/worker.py`; Rust launches it through the isolated interpreter and serializes jobs. No changes to the main meeting database schema are required. The worker decodes audio through Meetily's bundled FFmpeg and caps recordings at six hours. Analysis can take minutes for long meetings and currently has no cancel control.

## Models and attribution

The installer pins downloads by SHA-256 and retains the segmentation model's LICENSE and README in its models directory. Model files are downloaded from the official sherpa-onnx release assets; they are not included in the source patch or application ZIP.

- sherpa-onnx project and examples: https://github.com/k2-fsa/sherpa-onnx
- Segmentation documentation and release: https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/ and https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models
- 3D-Speaker project: https://github.com/modelscope/3D-Speaker
- Embedding model release: https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models

## Validation

```sh
# Use the installed isolated runtime, or another environment with the setup dependencies.
"$HOME/Library/Application Support/com.meetily.ai/speaker-recognition/venv/bin/python3" integrations/speakers/test_worker.py
node --test integrations/speakers/test_labels.cjs

# Optional: downloads official public test audio and runs real models in a temporary store.
"$HOME/Library/Application Support/com.meetily.ai/speaker-recognition/venv/bin/python3" integrations/speakers/smoke_reference_audio.py
```

Five worker tests cover ambiguous/invalid matches, overlap exclusion, persistence, cross-meeting recognition, profile rename/delete, short samples, and refusal of mixed-voice enrollment. Four transcript tests cover single/multiple voices, silence, invalid timestamps, and small boundary spill. Frontend type checking and the macOS release build pass.

Manual inference testing used official public reference samples, with enrollment and recognition on separate utterances and separate worker processes. Two enrolled references were matched successfully using the multilingual model. Some short reference clips were repeated to meet duration requirements; this is a functional smoke test, not an accuracy benchmark. Another edited two-voice sample was incorrectly merged by diarization and declined by the matcher. The updated application still needs live UI and real-meeting validation after replacing the installed app; the user requested that the current recording not be interrupted.
