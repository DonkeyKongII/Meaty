# Persistent local speaker recognition

This feature adds post-recording diarization and explicitly enrolled voice profiles to Meaty. It runs locally, with no inference API, meeting bot, or audio upload. It is implemented alongside Google Meet auto start on branch `feat/meeting-autostart`.

## Use

1. Open a saved meeting's **Meeting Details** tab and find **Speakers**.
2. Choose **Detect speakers**. For meetings, provide the known number of people who spoke (1–20). Leaving it blank uses experimental automatic clustering, which can over-split voices.
3. Listen to each sample and enter a name. **Save speaker** names the group for that meeting.
4. Check **Remember this voice in future meetings** to explicitly enroll a reusable profile. At least eight seconds of clear speech and a consistent voice group are required. Choose an existing person from the dropdown to explicitly replace that person's reference with the current voice.
5. Newly saved recordings queue automatic speaker analysis. Saved profiles are matched when analysis runs. Jobs wait while Meaty is recording, and failed analyses can be retried manually with **Detect speakers**.
6. Rename or delete saved profiles in **Saved voice profiles**. Deleting removes the reference vector and linked per-meeting enrollment vectors, while preserving historical labels, meeting recordings, and playback samples.

Names appear above timestamped transcript chunks. Chunks containing material portions of multiple speaker turns display multiple names. Legacy transcript rows without recording-relative timestamps are left unlabeled. These annotations do not yet change summary generation or transcript-copy/export output.

## Recognition behavior

- Local segmentation: sherpa-onnx's Pyannote segmentation 3.0 ONNX model.
- With a known count, reliable fragment embeddings are clustered globally using deterministic, duration-weighted spherical k-means. The native complete-link result is used to produce fragments rather than forcing its outliers into separate people. Fragments without sufficiently consistent voice material, or with low similarity to the final centers, remain `Unassigned speech`. This improves the observed count failure but is not validated as a general accuracy improvement.
- Local embedding: 3D-Speaker CAMPPlus Chinese/English common advanced ONNX model.
- A persistent local SQLite database stores model-versioned vectors, profile names, meeting analyses, and explicit corrections. Profiles survive application restarts and source rebuilds with the same app identity.
- Similarity is cosine similarity, not a calibrated probability. The initial match threshold is 0.65 with a 0.10 margin over the next person. Matching requires five seconds of usable material; enrollment requires eight.
- Overlapping speech is excluded from embedding material. Substantial disagreement between segment embeddings blocks enrollment and automatic naming for that group. This is a heuristic, not a guarantee of a clean or correct cluster.
- Automatic guesses never update voice profiles. Only an explicit enrollment updates a person's reference. An update currently replaces the reference; it does not maintain a multi-session voice gallery.
- Low scores, ambiguous matches, short speech, or inconsistent groups stay unnamed. There are still possible false matches and diarization errors. Listen before enrollment and correct mistakes; changed microphones, noise, overlap, and voice changes can affect results. Thresholds need validation on real meetings.
- Automatic results over 20 speakers, or explicit-count results above the requested count, are rejected before saving. This is a failure guard, not a speaker-estimation algorithm. Previously saved excessive results are flagged, hidden from transcript attribution, and blocked from enrollment until re-analysis. Changing the requested count bypasses cached analysis even without a forced retry. The requested count is saved and restored in the UI.
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

The application bundles `speaker_runtime/worker.py`; Rust launches it through the isolated interpreter and serializes jobs. No changes to the main meeting database schema are required. The worker decodes audio through Meaty's bundled FFmpeg and caps recordings at six hours. Analysis can take minutes for long meetings and currently has no cancel control.

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

Eleven worker tests cover ambiguous/invalid matches, overlap exclusion, persistence, cross-meeting recognition, profile rename/delete, short samples, and refusal of mixed-voice enrollment. Five transcript tests cover single/multiple voices, silence, invalid timestamps, and small boundary spill. Frontend type checking and the macOS release build pass.

Manual inference testing used official public reference samples, with enrollment and recognition on separate utterances and separate worker processes. Two enrolled references were matched successfully using the multilingual model. Some short reference clips were repeated to meet duration requirements; this is a functional smoke test, not an accuracy benchmark. Another edited two-voice sample was incorrectly merged by diarization and declined by the matcher. The updated application still needs live UI and real-meeting validation after replacing the installed app; the user requested that the current recording not be interrupted.


## Regression: eight-person meeting split into 111 clusters

The initial unconstrained complete-link clustering at a distance threshold of 0.5 over-split a real 35-minute meeting into 111 clusters. Short public audio tests did not reveal this failure. A roster of eight attendees establishes a cardinality constraint, not the identities of arbitrary output groups. A first fixed-k retry produced eight groups but merged most speech into three large groups, so simply forcing the native count was not accepted as a sufficient fix. The correction uses duration-weighted global fragment clustering for known counts, adds explicit-count validation, excessive-result rejection, safe cache invalidation, legacy-result warnings, and an opt-in default for automatic runs. The original recording is not modified and the prior analysis database is backed up before the affected meeting is re-analyzed with a count of eight. Group assignments still need listening review; eight output groups alone does not establish accurate diarization.

The corrected full run on the affected recording saved eight proposed groups, with 124.9 speech-segment seconds left unassigned. The source audio was not modified. This confirms the count and persistence behavior, not the identity accuracy of those eight groups; human listening review is still required.
