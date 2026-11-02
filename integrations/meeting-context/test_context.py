import importlib.util
from pathlib import Path
import sqlite3
import unittest
spec = importlib.util.spec_from_file_location('context', Path(__file__).resolve().parents[2] / 'frontend/src-tauri/context_runtime/context.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
class ContextTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript('CREATE TABLE meetings(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,folder_path TEXT); CREATE TABLE transcripts(meeting_id TEXT,transcript TEXT,audio_start_time REAL,audio_end_time REAL,timestamp TEXT);')
        self.db.executescript((Path(__file__).resolve().parents[2]/'frontend/src-tauri/migrations/20261102000000_meeting_context.sql').read_text())
        self.db.execute("INSERT INTO meetings VALUES('m','Call','2026-11-02','/recordings')")
        self.settings={'internal_domains': c.DEFAULT_DOMAINS,'company_names':{}}
    def tearDown(self): self.db.close()
    def people(self,*emails): return {'participants':[{'name':email.split('@')[0],'email':email} for email in emails]}
    def test_all_five_domains_are_internal(self):
        result=c.normalize(self.people(*['person@'+d for d in c.DEFAULT_DOMAINS]),self.settings)
        self.assertEqual(result['classification'],'internal'); self.assertEqual(result['confirmed_participants'],0)
    def test_spoofed_domain_is_external(self):
        self.assertEqual(c.normalize(self.people('a@hunters.ai.evil.com'),self.settings)['classification'],'external')
    def test_missing_emails_not_internal(self):
        self.assertEqual(c.normalize({'participants':[{'name':'Mukul'}]},self.settings)['classification'],'unknown')
    def test_multiple_companies_and_personal_domain(self):
        result=c.normalize(self.people('a@acme.com','b@example.com','c@gmail.com'),self.settings)
        self.assertEqual([v['domain'] for v in result['companies']],['acme.com','example.com'])
    def test_personal_email_not_gmail_company(self):
        result=c.normalize(self.people('a@gmail.com'),self.settings)
        self.assertEqual(result['classification'],'unknown');self.assertEqual(result['companies'],[])
    def test_queue_save_and_settings_reindex(self):
        c.run(self.db,{'action':'queue','meeting_id':'m'})
        self.assertEqual(len(c.run(self.db,{'action':'pending'})),1)
        c.run(self.db,{'action':'save','meeting_id':'m','data':self.people('vijay@acme.com')})
        self.assertEqual(c.run(self.db,{'action':'pending'}),[])
        c.run(self.db,{'action':'settings','data':{**self.settings,'company_names':{'acme.com':'Acme Inc'}}})
        text=self.db.execute('SELECT search_text FROM meeting_context').fetchone()[0]
        self.assertIn('vijay',text);self.assertIn('acme inc',text)
        self.db.execute("DELETE FROM meetings WHERE id='m'")
        self.assertEqual(c.run(self.db,{'action':'list'}),{})
    def test_unknown_meeting_rejected(self):
        with self.assertRaises(ValueError):c.run(self.db,{'action':'save','meeting_id':'no','data':{}})
if __name__=='__main__':unittest.main()
