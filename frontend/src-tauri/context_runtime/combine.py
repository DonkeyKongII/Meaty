"""Create a new combined recording. Originals and voice profiles are never modified."""
import datetime, json, math, shutil, subprocess, uuid, wave
from pathlib import Path

def combine(db, request, normalize, settings, search_text):
    ids=request.get('meeting_ids',[])
    title=str(request.get('title','')).strip()
    if not 2 <= len(ids) <= 10 or len(set(ids)) != len(ids):
        raise ValueError('Select 2 to 10 different meetings')
    if not title or len(title)>200: raise ValueError('Enter a meeting title (up to 200 characters)')
    def originals(mid, visiting=None):
        visiting=set(visiting or ())
        if mid in visiting: raise ValueError('Invalid combined meeting history')
        visiting.add(mid)
        row=db.execute('SELECT data FROM meeting_context WHERE meeting_id=?',(mid,)).fetchone()
        parts=json.loads(row[0]).get('combined_from',[]) if row else []
        if not parts:return {mid}
        return set().union(*(originals(p['meeting_id'],visiting) for p in parts))
    included=set()
    for selected in ids:
        parts=originals(selected)
        if included & parts: raise ValueError('These meetings contain overlapping recordings. Select each original recording only once.')
        included.update(parts)
    sources=[]
    for mid in ids:
        row=db.execute('SELECT * FROM meetings WHERE id=?',(mid,)).fetchone()
        if not row: raise ValueError('A selected meeting no longer exists')
        source=dict(row);folder=Path(source['folder_path']) if source.get('folder_path') else None
        meta=json.loads((folder/'metadata.json').read_text()) if folder and (folder/'metadata.json').exists() else {}
        if meta.get('status')=='recording': raise ValueError('Finish recording before combining meetings')
        transcripts=[dict(t) for t in db.execute('SELECT * FROM transcripts WHERE meeting_id=? ORDER BY COALESCE(audio_start_time,0),timestamp',(mid,))]
        if not transcripts: raise ValueError('Each selected meeting must have a saved transcript')
        sources.append((source,folder,meta,transcripts))
    base=next((folder.parent for _,folder,_,_ in sources if folder),Path.home()/'Movies/meetily-recordings')
    mid='meeting-'+str(uuid.uuid4());folder=base/('Combined_'+mid)
    folder.mkdir(parents=True,exist_ok=False)
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    include_audio=request.get('include_audio',True)
    offsets=[];segments=[];total=0.0;notes=[];participants={};companies=[];provenance=[];classifications=[]
    try:
        output=wave.open(str(folder/'audio.wav'),'wb') if include_audio else None
        try:
            if output: output.setparams((1,2,48000,0,'NONE','not compressed'))
            for index,(source,srcfolder,meta,transcripts) in enumerate(sources):
                duration=max(float(t.get('audio_end_time') or t.get('audio_start_time') or 0) for t in transcripts)
                duration=max(duration,float(meta.get('duration_seconds') or 0))
                if output:
                    candidates=[srcfolder/name for name in ['audio.mp4','audio.m4a','audio.wav','audio.mp3']] if srcfolder else []
                    audio=next((p for p in candidates if p.is_file()),None)
                    if not audio: raise ValueError('Missing audio for '+source['title']+'. Disable Include audio to combine transcripts only.')
                    temp=folder/'part.wav'
                    result=subprocess.run([request['ffmpeg_path'],'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(audio),'-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',str(temp)],capture_output=True,timeout=1800)
                    if result.returncode: raise ValueError('Unable to decode audio for '+source['title'])
                    with wave.open(str(temp),'rb') as part:
                        duration=part.getnframes()/48000
                        if any(float(t.get('audio_end_time') or 0)>duration+1 for t in transcripts):
                            raise ValueError('Transcript timing extends past source audio: '+source['title'])
                        while True:
                            frames=part.readframes(48000)
                            if not frames: break
                            output.writeframesraw(frames)
                    temp.unlink()
                if not math.isfinite(duration) or duration<=0: raise ValueError('Cannot determine recording duration for '+source['title'])
                offsets.append(total)
                for t in transcripts:
                    t['id']=str(uuid.uuid4());t['meeting_id']=mid
                    for key in ('audio_start_time','audio_end_time'):
                        if t.get(key) is not None: t[key]=float(t[key])+total
                    segments.append(t)
                row=db.execute('SELECT notes_markdown FROM meeting_notes WHERE meeting_id=?',(source['id'],)).fetchone()
                if row and row[0]: notes.append('## '+source['title']+'\n\n'+row[0])
                row=db.execute('SELECT data FROM meeting_context WHERE meeting_id=?',(source['id'],)).fetchone()
                context=json.loads(row[0]) if row else {}
                classifications.append(context.get('classification','unknown'))
                for person in context.get('participants',[]):
                    key=person.get('email') or (source['id'],person.get('name'))
                    if key not in participants or person.get('attendance')=='confirmed': participants[key]=person
                for c in context.get('manual_companies',[]):
                    if c.casefold() not in [v.casefold() for v in companies]:companies.append(c)
                provenance.append({'meeting_id':source['id'],'title':source['title'],'offset_seconds':total,'duration_seconds':duration,'created_at':source['created_at'],'folder_path':source.get('folder_path')})
                total+=duration
        finally:
            if output:output.close()
        external_names=[c for c in companies if c.casefold()!='internal']
        companies=external_names or (['Internal'] if companies and all(c=='internal' for c in classifications) else [])
        data=normalize({'participants':list(participants.values()),'unresolved_source_roster':any(c=='unknown' for c in classifications),'manual_companies':companies,'combined_from':provenance,'recording_started_at':sources[0][2].get('created_at',sources[0][0]['created_at']),'notes':'Combined recording; source meetings retained. Speaker assignments remain in the originals. Detect speakers for this combined recording before regenerating its summary.'},settings)
        metadata={'version':'1.0','meeting_id':mid,'meeting_name':title,'created_at':sources[0][2].get('created_at',sources[0][0]['created_at']),'completed_at':now,'duration_seconds':total,'devices':{'microphone':None,'system_audio':None},'audio_file':'audio.wav' if include_audio else '', 'transcript_file':'transcripts.json','sample_rate':48000,'status':'completed','combined_from':provenance}
        (folder/'metadata.json').write_text(json.dumps(metadata,indent=2))
        (folder/'transcripts.json').write_text(json.dumps([{'id':t['id'],'text':t['transcript'],'audio_start_time':t['audio_start_time'],'audio_end_time':t['audio_end_time'],'duration':t.get('duration') or 0,'display_time':t['timestamp'],'confidence':t.get('confidence') or 0.0,'sequence_id':i} for i,t in enumerate(segments)],indent=2))
        (folder/'combined-sources.json').write_text(json.dumps(provenance,indent=2))
        with db:
            db.execute('INSERT INTO meetings(id,title,created_at,updated_at,folder_path) VALUES(?,?,?,?,?)',(mid,title,now,now,str(folder)))
            for t in segments:
                columns=list(t);db.execute('INSERT INTO transcripts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[t[c] for c in columns])
            if notes:db.execute('INSERT INTO meeting_notes(meeting_id,notes_markdown,created_at,updated_at) VALUES(?,?,?,?)',(mid,'\n\n---\n\n'.join(notes),now,now))
            db.execute("INSERT INTO meeting_context(meeting_id,data,search_text,status) VALUES(?,?,?,'needs_review')",(mid,json.dumps(data),search_text(data)))
        return {'id':mid,'title':title,'folder_path':str(folder),'source_count':len(ids),'duration_seconds':total}
    except BaseException:
        shutil.rmtree(folder,ignore_errors=True)
        raise
