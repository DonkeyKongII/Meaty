#!/usr/bin/python3
"""Local meeting context store. Uses only Python standard library; no network access.
CLI: context.py --db PATH --request FILE (or JSON on stdin).
Calendar invitees are expected participants, never confirmed speakers.
"""
import argparse
import json
import sqlite3
import sys

DEFAULT_DOMAINS = ['hunters.ai', 'hunters.security', 'seamlesslabs.ai', 's10s.ai', 's10slabs.ai']
PERSONAL_DOMAINS = {'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'icloud.com', 'yahoo.com', 'live.com', 'proton.me', 'protonmail.com'}

def normalize(data, settings):
    if not isinstance(data, dict):
        raise ValueError('Context must be an object')
    people = []
    for raw in data.get('participants', []):
        email = str(raw.get('email', '')).strip().lower()
        if email and (email.count('@') != 1 or not all(email.split('@'))):
            raise ValueError('Invalid participant email')
        people.append({'name': str(raw.get('name', '')).strip()[:200], 'email': email,
                       'attendance': raw.get('attendance') if raw.get('attendance') in ('invited', 'confirmed') else 'invited'})
    domains = sorted({p['email'].split('@')[1] for p in people if p['email']})
    internal = set(settings.get('internal_domains', DEFAULT_DOMAINS))
    external = [d for d in domains if d not in internal]
    # Missing emails prevent a definitive Internal classification.
    known = bool(people) and all(p['email'] for p in people) and not data.get('unresolved_source_roster',False)
    classification = 'internal' if known and not external else ('external' if external else 'unknown')
    companies = [{'domain': d, 'name': settings.get('company_names', {}).get(d, d)} for d in external if d not in PERSONAL_DOMAINS]
    if any(d in PERSONAL_DOMAINS for d in external):
        classification = 'unknown' if not companies else 'external'
    manual = data.get('manual_companies', [])
    if not isinstance(manual, list) or any(not isinstance(v, str) for v in manual):
        raise ValueError('Company names must be a list of names')
    manual = list(dict.fromkeys(v.strip() for v in manual if v.strip()))
    if len(manual)>20 or any(len(v)>200 for v in manual): raise ValueError('Enter up to 20 company names, each up to 200 characters')
    if manual:
        companies = [{'domain':'', 'name':v} for v in manual]
        classification = 'internal' if len(manual)==1 and manual[0].casefold()=='internal' else 'external'
    result = {**data, 'manual_companies':manual, 'participants': people, 'classification': classification, 'companies': companies}
    result['calendar_title'] = str(data.get('calendar_title', ''))[:500]
    # Invitees do not establish the number of voices in the recording.
    result['expected_participants'] = len(people)
    result['confirmed_participants'] = sum(p['attendance'] == 'confirmed' for p in people)
    return result

def search_text(data):
    return ' '.join([data['classification'], data.get('calendar_title', '')] +
        [v for p in data['participants'] for v in (p['name'], p['email'])] +
        [v for c in data['companies'] for v in (c['name'], c['domain'])]).lower()

def run(db, request):
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    settings = json.loads(db.execute('SELECT data FROM meeting_context_settings WHERE id=1').fetchone()[0])
    action = request.get('action', 'get')
    mid = request.get('meeting_id')
    if action == 'settings':
        if 'data' in request:
            proposed = request['data']
            domains = [str(d).strip().lower() for d in proposed['internal_domains']]
            if not domains or any('@' in d or '.' not in d or '/' in d or ' ' in d for d in domains):
                raise ValueError('Enter valid internal email domains')
            settings = {'internal_domains': sorted(set(domains)), 'company_names': proposed.get('company_names', {})}
            db.execute('UPDATE meeting_context_settings SET data=? WHERE id=1', (json.dumps(settings),))
            for row in db.execute('SELECT meeting_id,data FROM meeting_context').fetchall():
                data = normalize(json.loads(row['data']), settings)
                db.execute('UPDATE meeting_context SET data=?, search_text=? WHERE meeting_id=?', (json.dumps(data), search_text(data), row['meeting_id']))
        db.commit()
        return settings
    if action == 'list':
        return {r['meeting_id']: {**json.loads(r['data']), 'status': r['status']} for r in db.execute('SELECT * FROM meeting_context')}
    if action == 'combine':
        from combine import combine
        return combine(db, request, normalize, settings, search_text)
    if action == 'candidates':
        from combine import recording_start
        rows=[dict(r) for r in db.execute('SELECT m.id,m.title,m.created_at,m.folder_path FROM meetings m WHERE EXISTS(SELECT 1 FROM transcripts t WHERE t.meeting_id=m.id)')]
        for row in rows: row['started_at']=recording_start(db,row).isoformat()
        return sorted(rows,key=lambda row:(row['started_at'],row['created_at'],row['id']))
    if action == 'pending':
        return [dict(r) for r in db.execute("SELECT m.id,m.title,m.created_at,m.folder_path,c.status FROM meeting_context c JOIN meetings m ON m.id=c.meeting_id WHERE c.status='pending' ORDER BY m.created_at LIMIT 10")]
    if not db.execute('SELECT 1 FROM meetings WHERE id=?', (mid,)).fetchone():
        raise ValueError('Meeting not found')
    row = db.execute('SELECT data,status FROM meeting_context WHERE meeting_id=?', (mid,)).fetchone()
    if action == 'get':
        return {**normalize(json.loads(row['data']) if row else {}, settings), 'status': row['status'] if row else 'not_queued'}
    if action == 'transcript':
        return [dict(r) for r in db.execute('SELECT transcript,audio_start_time,audio_end_time,timestamp FROM transcripts WHERE meeting_id=? ORDER BY COALESCE(audio_start_time,0),timestamp', (mid,))]
    if action == 'queue':
        db.execute("INSERT INTO meeting_context(meeting_id) VALUES(?) ON CONFLICT(meeting_id) DO UPDATE SET status='pending'", (mid,))
    elif action == 'save':
        proposed = dict(request['data'])
        # Calendar enrichment must preserve a manual company override unless explicitly edited.
        previous = json.loads(row['data']) if row else {}
        if 'manual_companies' not in proposed and 'manual_companies' in previous:
            proposed['manual_companies'] = previous['manual_companies']
        data = normalize(proposed, settings)
        status = request.get('status', 'complete')
        if status not in ('complete', 'needs_review'):
            raise ValueError('Invalid completion status')
        db.execute('INSERT INTO meeting_context(meeting_id,data,search_text,status) VALUES(?,?,?,?) ON CONFLICT(meeting_id) DO UPDATE SET data=excluded.data,search_text=excluded.search_text,status=excluded.status,updated_at=CURRENT_TIMESTAMP', (mid, json.dumps(data), search_text(data), status))
    else:
        raise ValueError('Unsupported action')
    db.commit()
    return run(db, {'action': 'get', 'meeting_id': mid})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--request')
    args = parser.parse_args()
    try:
        request = json.loads(open(args.request).read() if args.request else sys.stdin.read())
        # Never silently create a database on a mistyped path.
        with sqlite3.connect('file:' + args.db + '?mode=rw', uri=True, timeout=15) as db:
            print(json.dumps(run(db, request)))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        sys.exit(1)
