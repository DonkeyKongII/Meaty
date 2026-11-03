#!/usr/bin/python3
"""Export local meeting notes/transcripts for the Life portal. No audio or voice vectors.
Writes an ingest batch; it never touches the portal's Docker-owned database.
Codex separately extracts tasks and records the reviewed transcript fingerprint.

Batch contract: `exported_at` + `manifest` (every meeting id in the local DB,
regardless of --meeting-id filters) let the portal apply tombstones for meetings
deleted in Meaty; `pending_summaries` lets it show "summary in progress".
"""
import argparse,datetime,hashlib,json,re,sqlite3,sys
from pathlib import Path

# The portal rejects meeting notes/transcripts over 500,000 characters and
# payloads over 2 MB; enforce both here so one oversized meeting cannot fail
# the whole batch portal-side.
FIELD_CAP=490_000
PAYLOAD_CAP=1_800_000

def stamp(seconds):
    seconds=int(seconds or 0)
    return f'{seconds//60:02d}:{seconds%60:02d}'

def useful_title(title):
    title=str(title or '').strip()
    return bool(title) and not re.fullmatch(r'(?:Meeting[ _]\d[\d_ :./-]*|Untitled(?: Meeting)?|Meeting(?: Summary)?|Summary)',title,re.I)

def summary_title(saved_title, raw):
    # A deliberate user title takes precedence over a regenerated heading.
    if useful_title(saved_title):return saved_title.strip()
    for markdown in [raw.get('markdown',''),raw.get('english_cache',{}).get('markdown','')]:
        heading=re.search(r'^# +([^\n]+)',markdown,re.M)
        if heading and useful_title(heading[1]):return heading[1].strip()
    return None

def export(db_path, meeting_ids=None):
    # A file: URI fails to open paths containing spaces (e.g. the default
    # "Application Support" location) on this Python/SQLite build, so use a
    # plain connection with query_only for the same read-only guarantee.
    with sqlite3.connect(str(db_path),timeout=15) as db:
        db.execute('PRAGMA query_only=ON')
        db.row_factory=sqlite3.Row
        meetings=[]
        pending=[]
        warnings=[]
        all_ids=[r[0] for r in db.execute('SELECT id FROM meetings ORDER BY created_at')]
        for row in db.execute('SELECT * FROM meetings ORDER BY created_at'):
            m=dict(row);mid=m['id']
            if meeting_ids and mid not in meeting_ids:continue
            segments=[dict(t) for t in db.execute('SELECT transcript,audio_start_time,audio_end_time,timestamp FROM transcripts WHERE meeting_id=? ORDER BY COALESCE(audio_start_time,0),timestamp',(mid,))]
            transcript='\n'.join(f"[{stamp(t['audio_start_time'])}] {t['transcript']}" for t in segments)
            notes=db.execute('SELECT notes_markdown FROM meeting_notes WHERE meeting_id=?',(mid,)).fetchone()
            summary=db.execute('SELECT result,status FROM summary_processes WHERE meeting_id=?',(mid,)).fetchone()
            raw=json.loads(summary[0]) if summary and summary[0] else {}
            markdown=notes[0] if notes and notes[0] is not None else raw.get('markdown') or raw.get('english_cache',{}).get('markdown','')
            title=summary_title(m['title'],raw)
            status=summary[1] if summary else 'not_started'
            if status!='completed' or not markdown.strip() or not title:
                pending.append({'id':mid,'title':m['title'],'summary_status':status,'reason':'Waiting for a completed summary and descriptive title'})
                continue
            context=db.execute('SELECT data FROM meeting_context WHERE meeting_id=?',(mid,)).fetchone()
            context=json.loads(context[0]) if context else {}
            # Structured action items (table added 2026-11-03; older DBs lack it)
            try:
                action_items=[{'text':r[0],'completed':bool(r[1])} for r in db.execute('SELECT text,completed FROM action_items WHERE meeting_id=? ORDER BY created_at,rowid',(mid,))]
            except sqlite3.OperationalError:
                action_items=[]
            # The recording folder suffix is UTC start; creation time is save time.
            match=re.search(r'_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})$',m.get('folder_path') or '')
            started=f'{match[1]}T{match[2]}:{match[3]}:00+00:00' if match else context.get('recording_started_at') or context.get('calendar_source',{}).get('start') or m['created_at']
            fingerprint=hashlib.sha256(json.dumps(segments,sort_keys=True).encode()).hexdigest()
            duration=max((t['audio_end_time'] or 0) for t in segments) if segments else 0
            for field,value in [('notes',markdown),('transcript',transcript)]:
                if len(value)>FIELD_CAP:
                    warnings.append(f"{title}: {field} truncated from {len(value)} to {FIELD_CAP} characters to fit the portal cap")
                    if field=='notes':markdown=value[:FIELD_CAP]+f'\n\n… [truncated; full {len(value)}-character notes are in Meaty]'
                    else:transcript=value[:FIELD_CAP]+f'\n… [truncated; full {len(value)}-character transcript is in Meaty]'
            meetings.append({'id':mid,'title':title,'started_at':started,'duration_seconds':round(duration,1),'notes':markdown,'transcript':transcript,'participants':context.get('participants',[]),'companies':['Internal'] if context.get('classification')=='internal' else [c['name'] for c in context.get('companies',[])],'action_items':action_items, 'provenance':{'service':'meetily','saved_at':m['created_at'],'transcript_hash':fingerprint,'calendar':context.get('calendar_source'),'combined_from':context.get('combined_from',[])}})
        return {'exported_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'manifest':all_ids,'meetings':meetings,'tasks':[],'pending_summaries':pending,'warnings':warnings}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--db',type=Path,default=Path.home()/'Library/Application Support/com.meetily.ai/meeting_minutes.sqlite');p.add_argument('--meeting-id',action='append',help='Export only this meeting (repeatable)');args=p.parse_args()
    batch=export(args.db,args.meeting_id)
    payload=json.dumps(batch,indent=2)
    if len(payload.encode())>PAYLOAD_CAP:
        largest=sorted(batch['meetings'],key=lambda m:len(m['notes'])+len(m['transcript']),reverse=True)[:5]
        print(f'ERROR: batch is {len(payload.encode()):,} bytes, over the {PAYLOAD_CAP:,}-byte portal limit. Largest meetings:',file=sys.stderr)
        for m in largest:print(f"  {m['id']}  {m['title'][:60]}  {len(m['notes'])+len(m['transcript']):,} chars",file=sys.stderr)
        print('Re-run with --meeting-id to export subsets.',file=sys.stderr)
        sys.exit(1)
    Path(args.output).write_text(payload)
    for warning in batch['warnings']:print('WARNING:',warning,file=sys.stderr)
    print(f"Exported {len(batch['meetings'])} ready meetings to {args.output}; {len(batch['pending_summaries'])} waiting for summary/title. Not yet ingested.")
