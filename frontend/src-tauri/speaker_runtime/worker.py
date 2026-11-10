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
    best = {}
    for score, profile in scores:
        if profile['id'] not in best or score > best[profile['id']][0]: best[profile['id']] = (score, profile)
    scores = list(best.values())
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
    # A manually named transcript interval is not another detected voice.
    actual = sum(not speaker.get('id','').startswith('manual-') for speaker in result.get('speakers', []))
    expected = result.get('requested_speakers', -1)
    limit = MAX_AUTOMATIC_SPEAKERS if result.get('count_is_estimate') else (expected if expected > 0 else MAX_AUTOMATIC_SPEAKERS)
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


def estimate_speaker_count(speakers, expected):
    """Use an expected-size seed, then retain acoustically distinct extra voices."""
    import numpy as np
    if not speakers:
        return 0
    vectors = [np.asarray(s['embedding'], dtype=float) for s in sorted(speakers,key=lambda s:s['clean_seconds'],reverse=True)]
    vectors = [v/np.linalg.norm(v) for v in vectors if np.isfinite(v).all() and np.linalg.norm(v)>1e-8]
    centers=[]
    # Once the expected groups are present, require stronger separation before
    # adding extras. Missing invitees never force a fabricated voice group.
    for vector in vectors:
        threshold = .65 if len(centers) < expected else .5
        if not centers or max(float(vector @ center) for center in centers) < threshold:
            centers.append(vector)
    if len(centers)>MAX_AUTOMATIC_SPEAKERS:
        raise ValueError('Too many distinct voice groups; existing labels were preserved.')
    return len(centers)


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
        mapping = {speaker:str(i) for i,speaker in enumerate(sorted({turn['speaker'] for turn in turns},key=int))}
        for turn in turns: turn['speaker'] = mapping[turn['speaker']]
        speakers = []
        clips = root/'samples'/request['key']/str(uuid.uuid4())
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
    if count == -1 and len(speakers) > MAX_AUTOMATIC_SPEAKERS:
        # Sherpa's raw groups are often voice fragments, not individual people.
        # Estimate distinct voices from reliable fragment embeddings before validating.
        centers = [np.asarray(s['embedding'], dtype=float) for s in speakers
                   if s.get('embedding') and not s.get('mixed') and s['clean_seconds'] >= 3]
        centers = [v/np.linalg.norm(v) for v in centers if np.linalg.norm(v)>1e-8]
        while len(centers)>1:
            matrix=np.stack(centers) @ np.stack(centers).T
            np.fill_diagonal(matrix,-1)
            i,j=np.unravel_index(np.argmax(matrix),matrix.shape)
            if matrix[i,j]<.65: break
            center=centers[i]+centers[j];center/=np.linalg.norm(center)
            centers=[v for n,v in enumerate(centers) if n not in (i,j)]+[center]
        if not centers or len(centers)>MAX_AUTOMATIC_SPEAKERS:
            raise ValueError('Could not determine a reliable speaker count. Enter a known count to retry. Existing labels were preserved.')
        result = consolidate_fragments(result,len(centers))
        result['estimated_speakers']=len(centers)
        result['requested_speakers']=-1
    elif count > 0:
        # Expected attendance is a hint, never a hard cap on distinct voices.
        reliable = [v for v in speakers if v.get('embedding') and not v.get('mixed') and v['clean_seconds'] >= MIN_MATCH_SECONDS]
        target = estimate_speaker_count(reliable, count)
        if target:
            result = consolidate_fragments(result, target)
        result['requested_speakers']=count
        result['count_is_estimate']=True
    validate_turn_count(result['segments'], -1 if result.get('count_is_estimate') else count)
    return result


def profiles_from(db, ids=None, embeddings=True):
    columns='id,name,embedding' if embeddings else 'id,name'
    where='model=?'; args=[MODEL_ID]
    if ids is not None:
        ids=list(set(ids))
        if not ids: return []
        where+=' AND id IN ('+','.join('?' for _ in ids)+')';args+=ids
    profiles=[]
    for row in db.execute('SELECT '+columns+' FROM profiles WHERE '+where,args):
        profile={'id':row[0],'name':row[1]}
        if embeddings:profile['embedding']=json.loads(row[2])
        profiles.append(profile)
    if embeddings:
        for profile in list(profiles):
            for (encoded,) in db.execute('SELECT embedding FROM profile_samples WHERE profile_id=?',(profile['id'],)):
                profiles.append(dict(profile,embedding=json.loads(encoded)))
    return profiles


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
    linked={s.get('profile_id') for s in result['speakers']}
    result['profiles'] = [{'id':id,'name':name} for id,name in names.items() if id in linked]
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
        db.execute('CREATE INDEX IF NOT EXISTS profile_names ON profiles(name COLLATE NOCASE,id)')
        db.execute('CREATE TABLE IF NOT EXISTS profile_samples (profile_id TEXT, source TEXT, embedding TEXT NOT NULL, created_at INTEGER DEFAULT (unixepoch()), PRIMARY KEY(profile_id,source))')
        action = request['action']
        key = hashlib.sha256(request.get('meeting_id','').encode()).hexdigest()
        request['key'] = key
        row = db.execute('SELECT data FROM meetings WHERE id=?',(key,)).fetchone()
        result = json.loads(row[0]) if row else {'model':MODEL_ID,'segments':[],'speakers':[]}
        linked=[p.get('profile_id') for p in result['speakers'] if p.get('profile_id')]
        if request.get('profile_id'): linked.append(request['profile_id'])
        profiles = profiles_from(db, None if action=='analyze' else linked, embeddings=action=='analyze')
        if action=='search':
            query=str(request.get('query','')).strip()[:100]
            offset=max(0,min(int(request.get('offset',0)),1000000));limit=20
            pattern='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            rows=db.execute("SELECT id,name FROM profiles WHERE name LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE,id LIMIT ? OFFSET ?",(pattern,limit+1,offset)).fetchall()
            return {'items':[{'id':r[0],'name':r[1]} for r in rows[:limit]],'has_more':len(rows)>limit,'offset':offset,'total':db.execute('SELECT count(*) FROM profiles').fetchone()[0]}

        if action in ('forget','rename') and not any(profile['id']==request.get('profile_id') for profile in profiles):
            raise ValueError('The selected voice profile no longer exists.')
        if action == 'analyze':
            count = requested_count(request)
            if clustering_warning(result) and count == -1:
                raise ValueError('The previous automatic analysis over-split the voices. Enter the known speaker count to re-detect.')
            same_count = result.get('requested_speakers', -1) == count
            if row and any(not s['id'].startswith('manual-') for s in result.get('speakers',[])) and result.get('segments') and not request.get('force',False) and same_count:
                return {**public_result(result,profiles),'profile_count':db.execute('SELECT count(*) FROM profiles').fetchone()[0]}
            previous = result
            result = analyze(request, root)
            # Validate again at the persistence boundary, including alternate analyzers.
            validate_turn_count(result['segments'], -1 if result.get('count_is_estimate') else count)
            result['requested_speakers'] = count
            if clustering_warning(result):
                raise ValueError(clustering_warning(result))
            for speaker in result['speakers']:
                if speaker['embedding'] and not speaker.get('mixed') and speaker['clean_seconds'] >= MIN_MATCH_SECONDS:
                    profile, score = match_voice(speaker['embedding'], profiles)
                    speaker['score'] = score
                    if profile:
                        speaker.update(name=profile['name'],profile_id=profile['id'],status='recognized')
            manual = [s for s in previous.get('speakers',[]) if s['id'].startswith('manual-')]
            manual_ids = {s['id'] for s in manual}
            for span in previous.get('segments',[]):
                if span['speaker'] not in manual_ids: continue
                start,end=span['start'],span['end'];turns=[]
                for turn in result['segments']:
                    if turn['end']<=start or turn['start']>=end: turns.append(turn);continue
                    if turn['start']<start: turns.append(dict(turn,end=start))
                    if turn['end']>end: turns.append(dict(turn,start=end))
                turns.append(span)
                result['segments']=sorted(turns,key=lambda t:t['start'])
            result['speakers'].extend(manual)
        elif action == 'remove_tag':
            import math
            tag=json.loads(request.get('speaker_id','{}'))
            start,end=tag.get('start'),tag.get('end'); selected=tag.get('id')
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end)) or start<0 or end<=start or end-start>600:
                raise ValueError('Invalid transcript interval')
            if result.get('analysis_warning') or clustering_warning(result):
                raise ValueError('Review speaker detection before removing tags')
            exclusions=result.get('speaker_tag_exclusions',[])
            overlap={}
            for turn in result['segments']:
                duration=min(end,turn['end'])-max(start,turn['start'])
                if duration>0 and not any(x['speaker']==turn['speaker'] and x['start']==start and x['end']==end for x in exclusions):
                    overlap[turn['speaker']]=overlap.get(turn['speaker'],0)+duration
            maximum=max(overlap.values(),default=0)
            ids=[id for id,duration in overlap.items() if duration>=min(.25,maximum) and duration>=maximum*.2]
            voices={v['id']:v for v in result['speakers']}
            if selected not in ids or len(ids)<2 or voices.get(selected,{}).get('status','unknown')!='unknown' or not any(voices.get(id,{}).get('status','unknown') in ('manual','recognized') for id in ids if id!=selected):
                raise ValueError('Only unidentified tags alongside a known person can be removed')
            result['speaker_tag_exclusions']=exclusions+[{'start':start,'end':end,'speaker':selected}]
            result['learning_notice']='Speaker tag removed from this passage.'
        elif action in ('enroll','label','assign'):
            selected=request.get('speaker_id','')
            if action=='assign' and selected.startswith('__span__:'):
                import math
                _,start,end=selected.split(':');start=float(start);end=float(end)
                if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start or end-start>600:raise ValueError('Invalid transcript interval')
                group='manual-'+str(uuid.uuid4())
                turns=[]
                for turn in result['segments']:
                    if turn['end']<=start or turn['start']>=end:turns.append(turn);continue
                    if turn['start']<start:turns.append(dict(turn,end=start))
                    if turn['end']>end:turns.append(dict(turn,start=end))
                turns.append({'start':start,'end':end,'speaker':group})
                result['segments']=sorted(turns,key=lambda t:t['start'])
                result['speakers'].append({'id':group,'name':'Unidentified speaker','embedding':None,'mixed':False,'clean_seconds':0,'sample_path':None,'profile_id':None,'status':'unknown'})
                request['speaker_id']=group
            if clustering_warning(result):
                raise ValueError(clustering_warning(result))
            speaker = next((s for s in result['speakers'] if s['id']==request.get('speaker_id')), None)
            if not speaker:
                raise ValueError('Analyze the meeting and select a speaker first.')
            name = request.get('name','').strip()
            if not name or len(name)>100:
                raise ValueError('Enter a name between 1 and 100 characters.')
            previous_profile=speaker.get('profile_id')
            if previous_profile and previous_profile!=request.get('profile_id'):
                db.execute('DELETE FROM profile_samples WHERE profile_id=? AND source=?',(previous_profile,key+':'+speaker['id']))
            speaker.update(name=name,status='manual',profile_id=request.get('profile_id'))
            if request.get('profile_id') and not any(p['id']==request['profile_id'] for p in profiles):raise ValueError('The selected speaker no longer exists.')
            learning = action == 'enroll' or (action=='assign' and request.get('remember',True))
            eligible = bool(speaker.get('embedding')) and not speaker.get('mixed') and speaker['clean_seconds'] >= MIN_ENROLL_SECONDS
            if action == 'assign' and learning and not eligible:
                result['learning_notice']='Speaker assigned. This clip has too little clean speech to improve voice matching.'
            if action=='assign' and not request.get('profile_id') and not (learning and eligible):
                profile_id=str(uuid.uuid4())
                db.execute('INSERT INTO profiles VALUES (?,?,?,?)',(profile_id,name,MODEL_ID,'[]'))
                speaker['profile_id']=profile_id
            if action == 'enroll' or (learning and eligible):
                if speaker.get('mixed'):
                    raise ValueError('This speaker group may mix voices. Re-detect the speakers before saving a voice profile.')
                if not speaker['embedding'] or speaker['clean_seconds'] < MIN_ENROLL_SECONDS:
                    raise ValueError('A saved voice profile needs at least eight seconds of clear, non-overlapping speech.')
                profile_id = request.get('profile_id') or str(uuid.uuid4())
                if request.get('profile_id') and not any(p['id']==profile_id for p in profiles):
                    raise ValueError('The selected voice profile no longer exists.')
                # Add confirmed exemplars; retain the original anchor rather than replacing it.
                source=key+':'+speaker['id']
                db.execute('DELETE FROM profile_samples WHERE source=? AND profile_id!=?',(source,profile_id))
                db.execute('INSERT OR IGNORE INTO profiles VALUES (?,?,?,?)',(profile_id,name,MODEL_ID,'[]'))
                db.execute('INSERT OR REPLACE INTO profile_samples(profile_id,source,embedding) VALUES(?,?,?)',(profile_id,source,json.dumps(speaker['embedding'])))
                db.execute('DELETE FROM profile_samples WHERE profile_id=? AND source NOT IN (SELECT source FROM profile_samples WHERE profile_id=? ORDER BY created_at DESC,rowid DESC LIMIT 12)',(profile_id,profile_id))
                speaker['profile_id'] = profile_id
                result['learning_notice']='Speaker assigned. Confirmed voice sample saved for future matching.'
            if learning and eligible:
                refreshed_profiles = profiles_from(db)
                matched = 0
                for other in result['speakers']:
                    if other['status'] != 'unknown' or not other.get('embedding') or other.get('mixed') or other['clean_seconds'] < MIN_MATCH_SECONDS:
                        continue
                    profile, score = match_voice(other['embedding'], refreshed_profiles)
                    if profile:
                        other.update(name=profile['name'],profile_id=profile['id'],status='recognized',score=score)
                        matched += 1
                result['learning_notice'] += f' Checked other voices: {matched} matched.'
        elif action == 'rename':
            name=request.get('name','').strip()
            if not name or len(name)>100: raise ValueError('Enter a name between 1 and 100 characters.')
            db.execute('UPDATE profiles SET name=? WHERE id=?',(name,request.get('profile_id')))
        elif action == 'forget':
            forgotten = request.get('profile_id')
            db.execute('DELETE FROM profiles WHERE id=?',(forgotten,))
            db.execute('DELETE FROM profile_samples WHERE profile_id=?',(forgotten,))
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
        if action in ('analyze','enroll','label','assign','remove_tag'):
            db.execute('INSERT OR REPLACE INTO meetings VALUES (?,?)',(key,json.dumps(result)))
        profiles=profiles_from(db,[p.get('profile_id') for p in result['speakers']],embeddings=False)
        return {**public_result(result,profiles),'profile_count':db.execute('SELECT count(*) FROM profiles').fetchone()[0]}


if __name__ == '__main__':
    try:
        print(json.dumps(run(json.load(sys.stdin)), allow_nan=False))
    except Exception as error:
        print(json.dumps({'error':str(error)}))
        sys.exit(1)
