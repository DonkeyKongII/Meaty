#!/usr/bin/env python3
"""Local JSON API for background Meaty automation; never launches or focuses the app.

Usage: python3 automation_api.py status
       python3 automation_api.py request-summary --meeting-id ID
Summary requests use Meaty's existing durable queue, processed by the running app.
"""
import argparse
import json
import pathlib
import sqlite3

DEFAULT_DB = pathlib.Path.home() / 'Library/Application Support/com.meetily.ai/meeting_minutes.sqlite'

def status(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def rows(table, columns, where='1=1'):
        if table not in tables:
            return []
        return [dict(r) for r in db.execute(f'SELECT {columns} FROM {table} WHERE {where}')]
    return {'available': True,
            'pipeline': rows('meeting_pipeline', 'meeting_id,status,auto_summary,queued_at,error'),
            'summaries': rows('summary_processes', 'meeting_id,status'),
            'calendar_pending': [dict(r) for r in db.execute(
                "SELECT c.meeting_id,c.status,c.updated_at,m.title,m.created_at AS saved_at,m.folder_path "
                "FROM meeting_context c JOIN meetings m ON m.id=c.meeting_id "
                "WHERE c.status IN ('pending','processing') ORDER BY (json_extract(c.data,'$.lookup_requested_at') IS NOT NULL) DESC,CASE WHEN json_extract(c.data,'$.lookup_requested_at') IS NOT NULL THEN c.updated_at END DESC,m.created_at"
            )] if 'meeting_context' in tables else [],
            'calendar_instruction': 'Process up to 3 calendar_pending jobs BEFORE portal sync. Read recording metadata for the actual start time. Open the signed-in work calendars and save complete/needs_review, or record a concrete browser failure with retry count. A pending count alone is not a lookup attempt.',
            'speakers_active': rows('speaker_jobs', 'meeting_id,status', "status IN ('queued','running')")}

def request_summary(db, meeting_id):
    # BEGIN IMMEDIATE serializes requests with the app and other sync processes.
    db.execute('BEGIN IMMEDIATE')
    try:
        if not db.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone():
            raise ValueError('Unknown meeting')
        notes = db.execute('SELECT result FROM summary_processes WHERE meeting_id=?', (meeting_id,)).fetchone()
        if notes and notes[0] and notes[0].strip():
            db.rollback()
            return {'queued': False, 'reason': 'saved_notes', 'meeting_id': meeting_id}
        row = db.execute('SELECT status FROM summary_processes WHERE meeting_id=?', (meeting_id,)).fetchone()
        if row and row[0].lower() in ('completed', 'processing', 'pending', 'cancelled'):
            db.rollback()
            return {'queued': False, 'reason': row[0].lower(), 'meeting_id': meeting_id}
        # Never overwrite existing notes, including manually authored notes.
        # Queue only already-enrolled pipeline jobs: its schema and prerequisites belong to Meaty.
        row = db.execute('SELECT status FROM meeting_pipeline WHERE meeting_id=?', (meeting_id,)).fetchone()
        if not row:
            raise ValueError('Meeting has no automatic pipeline job; request a summary in Meaty once')
        if row[0] == 'cancelled':
            db.rollback()
            return {'queued': False, 'reason': 'cancelled', 'meeting_id': meeting_id}
        db.execute("UPDATE meeting_pipeline SET auto_summary=1,status='waiting',error=NULL WHERE meeting_id=?", (meeting_id,))
        db.commit()
        return {'queued': True, 'meeting_id': meeting_id, 'processor': 'running Meaty background pipeline'}
    except Exception:
        db.rollback()
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'request-summary'])
    parser.add_argument('--meeting-id')
    parser.add_argument('--db', type=pathlib.Path, default=DEFAULT_DB)
    args = parser.parse_args()
    if not args.db.exists():
        print(json.dumps({'available': False, 'reason': 'Meaty database not present'}))
        return
    if args.action == 'request-summary' and not args.meeting_id:
        parser.error('--meeting-id is required')
    mode = 'ro' if args.action == 'status' else 'rw'
    with sqlite3.connect(args.db.resolve().as_uri() + '?mode=' + mode, uri=True, timeout=5) as db:
        db.row_factory = sqlite3.Row
        result = status(db) if args.action == 'status' else request_summary(db, args.meeting_id)
    print(json.dumps(result))

if __name__ == '__main__':
    main()
