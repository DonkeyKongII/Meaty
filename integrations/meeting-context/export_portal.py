#!/usr/bin/python3
"""Export local meeting notes/transcripts for the Life portal. No audio or voice vectors.
Writes an ingest batch; it never touches the portal's Docker-owned database.
Codex separately extracts tasks and records the reviewed transcript fingerprint.
"""
import argparse,datetime,hashlib,json,re,sqlite3
from pathlib import Path

def stamp(seconds):
    seconds=int(seconds or 0)
    return f'{seconds//60:02d}:{seconds%60:02d}'

def export(db_path, meeting_ids=None):
    with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True,timeout=15) as db:
        db.row_factory=sqlite3.Row
        meetings=[]
        for row in db.execute('SELECT * FROM meetings ORDER BY created_at'):
            m=dict(row);mid=m['id']
            if meeting_ids and mid not in meeting_ids:continue
            segments=[dict(t) for t in db.execute('SELECT transcript,audio_start_time,audio_end_time,timestamp FROM transcripts WHERE meeting_id=? ORDER BY COALESCE(audio_start_time,0),timestamp',(mid,))]
            transcript='\n'.join(f"[{stamp(t['audio_start_time'])}] {t['transcript']}" for t in segments)
            notes=db.execute('SELECT notes_markdown FROM meeting_notes WHERE meeting_id=?',(mid,)).fetchone()
            summary=db.execute('SELECT result FROM summary_processes WHERE meeting_id=?',(mid,)).fetchone()
            raw=json.loads(summary[0]) if summary and summary[0] else {}
            markdown=notes[0] if notes and notes[0] is not None else raw.get('markdown') or raw.get('english_cache',{}).get('markdown','')
            context=db.execute('SELECT data FROM meeting_context WHERE meeting_id=?',(mid,)).fetchone()
            context=json.loads(context[0]) if context else {}
            # The recording folder suffix is UTC start; creation time is save time.
            match=re.search(r'_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})$',m.get('folder_path') or '')
            started=f'{match[1]}T{match[2]}:{match[3]}:00+00:00' if match else context.get('calendar_source',{}).get('start') or m['created_at']
            fingerprint=hashlib.sha256(json.dumps(segments,sort_keys=True).encode()).hexdigest()
            meetings.append({'id':mid,'title':m['title'],'started_at':started,'notes':markdown,'transcript':transcript,'participants':context.get('participants',[]),'companies':['Internal'] if context.get('classification')=='internal' else [c['name'] for c in context.get('companies',[])], 'provenance':{'service':'meetily','saved_at':m['created_at'],'transcript_hash':fingerprint,'calendar':context.get('calendar_source')}})
        return {'meetings':meetings,'tasks':[]}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--db',type=Path,default=Path.home()/'Library/Application Support/com.meetily.ai/meeting_minutes.sqlite');p.add_argument('--meeting-id',action='append',help='Export only this meeting (repeatable)');args=p.parse_args()
    batch=export(args.db,args.meeting_id)
    Path(args.output).write_text(json.dumps(batch,indent=2))
    print(f"Exported {len(batch['meetings'])} meeting notes to {args.output}; not yet ingested.")
