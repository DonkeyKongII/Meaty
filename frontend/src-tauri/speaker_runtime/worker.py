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
MAX_AUTOMATIC_SPEAKERS = 20


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



def requested_count(request):
    count = request.get('num_speakers', -1)
    if type(count) is not int or (count != -1 and not 1 <= count <= 20):
        raise ValueError('Enter a speaker count from 1 to 20, or -1 for experimental automatic detection.')
    return count


def clustering_warning(result):
    actual = len(result.get('speakers', []))
    expected = result.get('requested_speakers', -1)
    limit = expected if expected > 0 else MAX_AUTOMATIC_SPEAKERS
    if actual > limit:
        return (f'Speaker detection split this recording into {actual} groups. '
                'This result is unreliable. Enter the known number of speakers and re-detect before naming or saving voices.')
    return None


def validate_turn_count(turns, count):
    actual = len({turn['speaker'] for turn in turns if turn['speaker'] != '__unassigned__'})
    limit = count if count > 0 else MAX_AUTOMATIC_SPEAKERS
    if actual > limit:
        raise ValueError(f'Speaker clustering produced {actual} groups, exceeding {limit}. '
                         'No new analysis was saved. Enter the known number of speakers and re-detect.')
    return actual


def consolidate_fragments(result, count):
    """Cluster reliable fragment vectors globally; abstain on short/noisy fragments.

    Complete-link cutting with a fixed k can spend clusters on acoustic outliers.
    Duration-weighted spherical k-means instead fits the reliable speech vectors.
    This does not establish identities: users still review samples before naming.
    """
    import numpy as np
    candidates = [speaker for speaker in result['speakers']
                  if speaker.get('embedding') and not speaker.get('mixed')
                  and speaker['clean_seconds'] >= 3]
    if len(candidates) < count:
        raise ValueError(f'Only {len(candidates)} reliable voice fragments were available for {count} speakers. '
                         'No new analysis was saved. Review the recording or try a lower count if some attendees did not speak.')
    vectors = np.asarray([speaker['embedding'] for speaker in candidates], dtype=float)
    norms = np.linalg.norm(vectors, axis=1)
    if not np.isfinite(vectors).all() or (norms < 1e-8).any():
        raise ValueError('Invalid voice embeddings; no new analysis was saved.')
    vectors /= norms[:, None]
    weights = np.asarray([min(speaker['clean_seconds'], 60) for speaker in candidates])
    seeds = [int(np.argmax(weights))]
    while len(seeds) < count:
        distance = np.maximum(0, 1-(vectors @ vectors[seeds].T).max(axis=1))
        scores = weights * distance**2
        scores[seeds] = -1
        next_seed = int(np.argmax(scores))
        if scores[next_seed] <= 1e-8:
            raise ValueError('There are fewer distinct usable voices than the requested count.')
        seeds.append(next_seed)
    centers = vectors[seeds].copy()
    previous = None
    for _ in range(100):
        assignment = np.argmax(vectors @ centers.T, axis=1)
        if previous is not None and np.array_equal(previous, assignment):
            break
        previous = assignment.copy()
        for cluster in range(count):
            mask = assignment == cluster
            if not mask.any():
                raise ValueError('A speaker group has no reliable speech. Try a lower count.')
            center = (vectors[mask] * weights[mask, None]).sum(axis=0)
            centers[cluster] = center / np.linalg.norm(center)
    similarity = (vectors * centers[assignment]).sum(axis=1)
    by_fragment = {speaker['id']:int(assignment[i]) for i,speaker in enumerate(candidates) if similarity[i] >= .55}
    first_turn = {cluster:min((turn['start'] for turn in result['segments'] if by_fragment.get(turn['speaker']) == cluster), default=float('inf')) for cluster in range(count)}
    order = sorted(first_turn, key=first_turn.get)
    ids = {cluster:str(i) for i,cluster in enumerate(order)}
    speakers = []
    for cluster in order:
        members = [i for i,speaker in enumerate(candidates) if by_fragment.get(speaker['id']) == cluster]
        if not members:
            raise ValueError('A speaker group has no confident voice material. No new analysis was saved.')
        representative = max(members, key=lambda i:weights[i]*similarity[i]**2)
        selected_weight = weights[members]
        mixed = float(selected_weight[similarity[members]<.6].sum()) > float(selected_weight.sum())*.2
        speakers.append({'id':ids[cluster], 'name':'Speaker '+str(len(speakers)+1),
                         'embedding':centers[cluster].tolist(), 'mixed':mixed,
                         'clean_seconds':round(sum(candidates[i]['clean_seconds'] for i in members),1),
                         'sample_path':candidates[representative].get('sample_path'),
                         'profile_id':None, 'status':'unknown', 'score':None})
    turns = []
    for turn in result['segments']:
        mapped = dict(turn, speaker=ids[by_fragment[turn['speaker']]] if turn['speaker'] in by_fragment else '__unassigned__')
        if turns and turns[-1]['speaker']==mapped['speaker'] and mapped['start']<=turns[-1]['end']+.25:
            turns[-1]['end'] = max(turns[-1]['end'],mapped['end'])
        else:
            turns.append(mapped)
    return dict(result, speakers=speakers, segments=turns, requested_speakers=count,
                clustering_method='duration-weighted-spherical-v1', source_fragments=len(result['speakers']),
                unassigned_seconds=round(sum(turn['end']-turn['start'] for turn in turns if turn['speaker']=='__unassigned__'),1))


def analyze(request, root):
    count = requested_count(request)
    import numpy as np
    import sherpa_onnx as sherpa
    import soundfile as sf
    models = root / 'models'
    config = sherpa.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(models/'segmentation.onnx')),
            num_threads=2),
        embedding=sherpa.SpeakerEmbeddingExtractorConfig(model=str(models/'embedding.onnx'), num_threads=2),
        clustering=sherpa.FastClusteringConfig(num_clusters=-1, threshold=.5),
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
        if count == -1:
            validate_turn_count(turns, count)
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
    result = {'model':MODEL_ID,'requested_speakers':count,'segments':turns,'speakers':speakers}
    if count > 0:
        result = consolidate_fragments(result, count)
    validate_turn_count(result['segments'], count)
    return result


def profiles_from(db):
    return [{'id':row[0], 'name':row[1], 'embedding':json.loads(row[2])} for row in db.execute('SELECT id,name,embedding FROM profiles WHERE model=?',(MODEL_ID,))]


def public_result(result, profiles):
    result = json.loads(json.dumps(result))
    warning = clustering_warning(result)
    result['analysis_warning'] = warning
    names = {profile['id']:profile['name'] for profile in profiles}
    for speaker in result['speakers']:
        speaker['can_enroll'] = not warning and bool(speaker.get('embedding')) and not speaker.get('mixed') and speaker['clean_seconds'] >= MIN_ENROLL_SECONDS
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
            count = requested_count(request)
            if clustering_warning(result) and count == -1:
                raise ValueError('The previous automatic analysis over-split the voices. Enter the known speaker count to re-detect.')
            same_count = result.get('requested_speakers', -1) == count
            if row and not request.get('force',False) and same_count:
                return public_result(result,profiles)
            result = analyze(request, root)
            # Validate again at the persistence boundary, including alternate analyzers.
            validate_turn_count(result['segments'], count)
            result['requested_speakers'] = count
            if clustering_warning(result):
                raise ValueError(clustering_warning(result))
            for speaker in result['speakers']:
                if speaker['embedding'] and not speaker.get('mixed') and speaker['clean_seconds'] >= MIN_MATCH_SECONDS:
                    profile, score = match_voice(speaker['embedding'], profiles)
                    speaker['score'] = score
                    if profile:
                        speaker.update(name=profile['name'],profile_id=profile['id'],status='recognized')
        elif action in ('enroll','label'):
            if clustering_warning(result):
                raise ValueError(clustering_warning(result))
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
