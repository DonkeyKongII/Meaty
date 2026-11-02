"""Offline speaker diarization and explicitly enrolled, local voice profiles."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import uuid

MODEL_ID = 'sherpa-campplus-zh-en-common-16k-v1'
MATCH_THRESHOLD = 0.65
MATCH_MARGIN = 0.10
MIN_ENROLL_SECONDS = 8.0
MIN_MATCH_SECONDS = 5.0


def match_voice(embedding, profiles):
    import numpy as np
    vector = np.asarray(embedding, dtype=float)
    norm = np.linalg.norm(vector)
    if not np.isfinite(vector).all() or norm < 1e-8:
        return None, None
    scores = []
    for profile in profiles:
        other = np.asarray(profile['embedding'], dtype=float)
        if other.shape != vector.shape or not np.isfinite(other).all():
            continue
        denominator = norm * np.linalg.norm(other)
        if denominator > 1e-8:
            scores.append((float(np.dot(vector, other) / denominator), profile))
    scores.sort(key=lambda item: item[0], reverse=True)
    if not scores:
        return None, None
    score, profile = scores[0]
    if score < MATCH_THRESHOLD or (len(scores) > 1 and score - scores[1][0] < MATCH_MARGIN):
        return None, score
    return profile, score


def clean_intervals(segment, all_segments):
    """Subtract other speakers' overlapping turns from enrollment material."""
    intervals = [(segment['start'], segment['end'])]
    for other in all_segments:
        if other['speaker'] == segment['speaker']:
            continue
        remaining = []
        for start, end in intervals:
            if other['end'] <= start or other['start'] >= end:
                remaining.append((start, end))
            else:
                if other['start'] > start:
                    remaining.append((start, min(end, other['start'])))
                if other['end'] < end:
                    remaining.append((max(start, other['end']), end))
        intervals = remaining
    return [(start + .1, end - .1) for start, end in intervals if end - start >= .7]


def analyze(request, root):
    import numpy as np
    import sherpa_onnx as sherpa
    import soundfile as sf
    models = root / 'models'
    config = sherpa.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(models/'segmentation.onnx')),
            num_threads=2),
        embedding=sherpa.SpeakerEmbeddingExtractorConfig(model=str(models/'embedding.onnx'), num_threads=2),
        clustering=sherpa.FastClusteringConfig(num_clusters=request.get('num_speakers', -1), threshold=.5),
        min_duration_on=.3, min_duration_off=.5)
    if not config.validate():
        raise ValueError('Speaker models are missing or invalid. Run integrations/speakers/setup.py.')
    diarizer = sherpa.OfflineSpeakerDiarization(config)
    extractor = sherpa.SpeakerEmbeddingExtractor(config.embedding)
    with tempfile.TemporaryDirectory(prefix='analysis-', dir=root) as temp:
        wav = Path(temp)/'audio.wav'
        process = subprocess.run([request['ffmpeg'], '-nostdin', '-v', 'error', '-i', request['audio'], '-ar', '16000', '-ac', '1', '-t', str(6*3600+1), '-y', str(wav)], capture_output=True, timeout=600)
        if process.returncode:
            raise ValueError('Could not decode meeting audio: '+process.stderr.decode(errors='replace')[-500:])
        samples, rate = sf.read(wav, dtype='float32')
        if not len(samples):
            raise ValueError('The recording contains no audio.')
        if len(samples)/rate > 6*3600:
            raise ValueError('Speaker analysis currently supports recordings up to six hours.')
        turns = [{'start':float(turn.start), 'end':float(turn.end), 'speaker':str(turn.speaker)} for turn in diarizer.process(samples).sort_by_start_time()]
        mapping = {speaker:str(i) for i,speaker in enumerate(sorted({turn['speaker'] for turn in turns},key=int))}
        for turn in turns: turn['speaker'] = mapping[turn['speaker']]
        speakers = []
        clips = root/'samples'/request['key']
        clips.mkdir(parents=True, exist_ok=True, mode=0o700)
        for speaker in sorted({turn['speaker'] for turn in turns}, key=int):
            intervals = [interval for turn in turns if turn['speaker']==speaker for interval in clean_intervals(turn, turns)]
            chunks = []
            seconds = 0.
            for start, end in sorted(intervals, key=lambda interval:interval[1]-interval[0], reverse=True):
                chunk = samples[int(start*rate):int(min(end, start+20)*rate)]
                chunks.append(chunk); seconds += len(chunk)/rate
                if seconds >= 60:
                    break
            vector = None
            preview = None
            mixed = False
            candidates = []
            for chunk in chunks:
                if len(chunk)/rate < 1.5:
                    continue
                stream = extractor.create_stream()
                stream.accept_waveform(sample_rate=rate, waveform=chunk)
                stream.input_finished()
                if extractor.is_ready(stream):
                    embedding = np.asarray(extractor.compute(stream))
                    norm = np.linalg.norm(embedding)
                    if np.isfinite(embedding).all() and norm > 1e-8:
                        candidates.append((chunk,embedding/norm))
            if candidates:
                vectors = np.stack([item[1] for item in candidates])
                similarity = vectors @ vectors.T
                durations = np.array([len(item[0])/rate for item in candidates])
                support = similarity >= .5
                medoid = int(np.argmax(support @ durations))
                keep = support[medoid]
                mixed = float(durations[keep].sum()) < float(durations.sum())*.8
                accepted = [item[0] for i,item in enumerate(candidates) if keep[i]]
                seconds = sum(len(chunk)/rate for chunk in accepted)
                stream = extractor.create_stream()
                stream.accept_waveform(sample_rate=rate, waveform=np.concatenate(accepted))
                stream.input_finished()
                if extractor.is_ready(stream):
                    vector = np.asarray(extractor.compute(stream)).tolist()
                    preview = str(clips/(speaker+'.wav'))
                    sf.write(preview, accepted[0][:rate*12], rate)
                    os.chmod(preview, 0o600)
            speakers.append({'id':speaker,'name':'Speaker '+str(int(speaker)+1),'embedding':vector,'mixed':mixed,'clean_seconds':round(seconds,1),'sample_path':preview,'profile_id':None,'status':'unknown','score':None})
    return {'model':MODEL_ID,'segments':turns,'speakers':speakers}


def profiles_from(db):
    return [{'id':row[0], 'name':row[1], 'embedding':json.loads(row[2])} for row in db.execute('SELECT id,name,embedding FROM profiles WHERE model=?',(MODEL_ID,))]


def public_result(result, profiles):
    result = json.loads(json.dumps(result))
    names = {profile['id']:profile['name'] for profile in profiles}
    for speaker in result['speakers']:
        speaker['can_enroll'] = bool(speaker.get('embedding')) and not speaker.get('mixed') and speaker['clean_seconds'] >= MIN_ENROLL_SECONDS
        speaker.pop('embedding', None)
        if speaker.get('profile_id') in names:
            speaker['name'] = names[speaker['profile_id']]
    result['profiles'] = [{'id':p['id'],'name':p['name']} for p in profiles]
    return result


def run(request):
    root = Path(request['root'])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    database = root/'voices.sqlite'
    with sqlite3.connect(database, timeout=60) as db:
        db.execute('PRAGMA secure_delete=ON')
        os.chmod(database, 0o600)
        db.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL, embedding TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS meetings (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        action = request['action']
        key = hashlib.sha256(request.get('meeting_id','').encode()).hexdigest()
        request['key'] = key
        row = db.execute('SELECT data FROM meetings WHERE id=?',(key,)).fetchone()
        result = json.loads(row[0]) if row else {'model':MODEL_ID,'segments':[],'speakers':[]}
        profiles = profiles_from(db)
        if action in ('forget','rename') and not any(profile['id']==request.get('profile_id') for profile in profiles):
            raise ValueError('The selected voice profile no longer exists.')
        if action == 'analyze':
            if row and not request.get('force',False):
                return public_result(result,profiles)
            result = analyze(request, root)
            for speaker in result['speakers']:
                if speaker['embedding'] and not speaker.get('mixed') and speaker['clean_seconds'] >= MIN_MATCH_SECONDS:
                    profile, score = match_voice(speaker['embedding'], profiles)
                    speaker['score'] = score
                    if profile:
                        speaker.update(name=profile['name'],profile_id=profile['id'],status='recognized')
        elif action in ('enroll','label'):
            speaker = next((s for s in result['speakers'] if s['id']==request.get('speaker_id')), None)
            if not speaker:
                raise ValueError('Analyze the meeting and select a speaker first.')
            name = request.get('name','').strip()
            if not name or len(name)>100:
                raise ValueError('Enter a name between 1 and 100 characters.')
            speaker.update(name=name,status='manual',profile_id=None)
            if action == 'enroll':
                if speaker.get('mixed'):
                    raise ValueError('This speaker group may mix voices. Re-detect the speakers before saving a voice profile.')
                if not speaker['embedding'] or speaker['clean_seconds'] < MIN_ENROLL_SECONDS:
                    raise ValueError('A saved voice profile needs at least eight seconds of clear, non-overlapping speech.')
                profile_id = request.get('profile_id') or str(uuid.uuid4())
                if request.get('profile_id') and not any(p['id']==profile_id for p in profiles):
                    raise ValueError('The selected voice profile no longer exists.')
                # Explicit enrollment only. Never learn from an automatic guess.
                db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?,?,?)',(profile_id,name,MODEL_ID,json.dumps(speaker['embedding'])))
                speaker['profile_id'] = profile_id
        elif action == 'rename':
            name=request.get('name','').strip()
            if not name or len(name)>100: raise ValueError('Enter a name between 1 and 100 characters.')
            db.execute('UPDATE profiles SET name=? WHERE id=?',(name,request.get('profile_id')))
        elif action == 'forget':
            forgotten = request.get('profile_id')
            db.execute('DELETE FROM profiles WHERE id=?',(forgotten,))
            for stored_key, encoded in db.execute('SELECT id,data FROM meetings').fetchall():
                stored = json.loads(encoded)
                for speaker in stored['speakers']:
                    if speaker.get('profile_id') == forgotten:
                        speaker.update(embedding=None,profile_id=None,status='manual',score=None)
                db.execute('UPDATE meetings SET data=? WHERE id=?',(json.dumps(stored),stored_key))
                if stored_key == key:
                    result = stored
        elif action != 'get':
            raise ValueError('Unsupported speaker action.')
        if action in ('analyze','enroll','label'):
            db.execute('INSERT OR REPLACE INTO meetings VALUES (?,?)',(key,json.dumps(result)))
        profiles=profiles_from(db)
        return public_result(result,profiles)


if __name__ == '__main__':
    try:
        print(json.dumps(run(json.load(sys.stdin)), allow_nan=False))
    except Exception as error:
        print(json.dumps({'error':str(error)}))
        sys.exit(1)
