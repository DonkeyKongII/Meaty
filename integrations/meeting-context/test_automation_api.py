import importlib.util
from pathlib import Path
import sqlite3
import unittest

spec = importlib.util.spec_from_file_location('automation_api', Path(__file__).with_name('automation_api.py'))
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

class CalendarQueueTests(unittest.TestCase):
    def test_status_returns_actionable_jobs_in_queue_order(self):
        with sqlite3.connect(':memory:') as db:
            db.row_factory = sqlite3.Row
            db.executescript("""
                CREATE TABLE meetings(id TEXT,title TEXT,created_at TEXT,folder_path TEXT);
                CREATE TABLE meeting_context(meeting_id TEXT,status TEXT,updated_at TEXT,data TEXT NOT NULL DEFAULT '{}');
                INSERT INTO meetings VALUES('later','Later','2026-11-04','/recordings/later'),('first','First','2026-11-03','/recordings/first'),('done','Done','2026-11-02','/recordings/done');
                INSERT INTO meeting_context(meeting_id,status,updated_at) VALUES('later','pending','2026-11-04'),('first','pending','2026-11-03'),('done','complete','2026-11-02');
            """)
            result = api.status(db)
            self.assertEqual([j['meeting_id'] for j in result['calendar_pending']], ['first','later'])
            self.assertEqual(result['calendar_pending'][0]['folder_path'], '/recordings/first')
            self.assertEqual(result['calendar_pending'][0]['saved_at'], '2026-11-03')
            self.assertIn('BEFORE portal sync', result['calendar_instruction'])

    def test_status_handles_database_before_context_migration(self):
        with sqlite3.connect(':memory:') as db:
            db.row_factory = sqlite3.Row
            self.assertEqual(api.status(db)['calendar_pending'], [])

if __name__ == '__main__':
    unittest.main()
