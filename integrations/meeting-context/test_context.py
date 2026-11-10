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
        self.db.execute('CREATE TABLE summary_processes(meeting_id TEXT,result TEXT)')
        self.db.executescript((Path(__file__).resolve().parents[2]/'frontend/src-tauri/migrations/20261103000002_meeting_title_source.sql').read_text())
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
    def test_manual_company_survives_calendar_enrichment_and_settings(self):
        c.run(self.db,{'action':'save','meeting_id':'m','data':{'manual_companies':['Snowflake']}})
        c.run(self.db,{'action':'save','meeting_id':'m','data':self.people('a@hunters.ai')})
        c.run(self.db,{'action':'settings','data':self.settings})
        data=c.run(self.db,{'action':'get','meeting_id':'m'})
        self.assertEqual(data['companies'],[{'domain':'','name':'Snowflake'}]);self.assertEqual(data['classification'],'external')
        c.run(self.db,{'action':'save','meeting_id':'m','data':{**data,'manual_companies':[]}})
        self.assertEqual(c.run(self.db,{'action':'get','meeting_id':'m'})['classification'],'internal')
    def test_manual_internal_without_invented_participants(self):
        data=c.normalize({'manual_companies':['Internal']},self.settings)
        self.assertEqual(data['classification'],'internal');self.assertEqual(data['expected_participants'],0)

    def test_calendar_title_replaces_generated_name_but_manual_name_wins(self):
        self.db.execute("UPDATE meetings SET title='AI heading',title_source='ai' WHERE id='m'")
        request={'action':'save','meeting_id':'m','data':{'calendar_title':'Calendar sync'}}
        c.run(self.db,request)
        self.assertEqual(tuple(self.db.execute("SELECT title,title_source FROM meetings WHERE id='m'").fetchone()),('Calendar sync','calendar'))
        self.db.execute("UPDATE meetings SET title='My title',title_source='manual' WHERE id='m'")
        c.run(self.db,request)
        self.assertEqual(self.db.execute("SELECT title FROM meetings WHERE id='m'").fetchone()[0],'My title')

    def test_migration_versions_are_unique(self):
        paths=list((Path(__file__).resolve().parents[2]/'frontend/src-tauri/migrations').glob('*.sql'))
        versions=[p.name.split('_',1)[0] for p in paths]
        self.assertEqual(len(versions),len(set(versions)), 'Every migration must have a distinct version')

    def test_classification_override_preserves_calendar_evidence_and_pending_lookup(self):
        original={**self.people('guest@acme.com'),'calendar_title':'Customer sync','notes':'Calendar evidence'}
        c.run(self.db,{'action':'save','meeting_id':'m','data':original})
        c.run(self.db,{'action':'queue','meeting_id':'m'})
        internal=c.run(self.db,{'action':'classify','meeting_id':'m','manual_companies':['Internal']})
        self.assertEqual(internal['classification'],'internal')
        self.assertEqual(internal['status'],'pending')
        self.assertEqual(internal['participants'][0]['email'],'guest@acme.com')
        self.assertEqual(internal['calendar_title'],'Customer sync')
        customer=c.run(self.db,{'action':'classify','meeting_id':'m','manual_companies':['Snowflake']})
        self.assertEqual(customer['companies'],[{'domain':'','name':'Snowflake'}])
        c.run(self.db,{'action':'save','meeting_id':'m','data':original})
        self.assertEqual(c.run(self.db,{'action':'get','meeting_id':'m'})['companies'],customer['companies'])
        automatic=c.run(self.db,{'action':'classify','meeting_id':'m','manual_companies':[]})
        self.assertEqual(automatic['companies'][0]['name'],'acme.com')

    def suggest(self):
        return c.run(self.db,{'action':'save','meeting_id':'m','status':'needs_review','data':{'calendar_title':'Possible sync','recommendations':{'title':{'value':'Suggested sync','reason':'Matching time'},'customer':{'value':'Acme','reason':'Customer evidence'}}}})
    def test_review_does_not_apply_uncertain_title_and_individual_choices_persist(self):
        first=self.suggest()
        self.assertEqual(first['meeting_title'],'Call')
        accepted=c.run(self.db,{'action':'review_recommendations','meeting_id':'m','decisions':{'title':{'action':'accept','expected':'Suggested sync','value':'Edited sync'}}})
        self.assertEqual(accepted['meeting_title'],'Edited sync')
        self.assertEqual(accepted['recommendations']['customer']['state'],'pending')
        dismissed=c.run(self.db,{'action':'review_recommendations','meeting_id':'m','decisions':{'customer':{'action':'dismiss','expected':'Acme'}}})
        self.assertEqual(dismissed['recommendations']['customer']['state'],'dismissed')
        refreshed=self.suggest()
        self.assertEqual(refreshed['recommendations']['customer']['state'],'dismissed')
        self.assertEqual(refreshed['meeting_title'],'Edited sync')
    def test_accept_both_is_atomic_and_dismiss_both_preserves_values(self):
        self.suggest()
        invalid={'title':{'action':'accept','expected':'Suggested sync'},'customer':{'action':'accept','expected':'Acme','value':''}}
        with self.assertRaises(ValueError):c.run(self.db,{'action':'review_recommendations','meeting_id':'m','decisions':invalid})
        self.assertEqual(c.run(self.db,{'action':'get','meeting_id':'m'})['meeting_title'],'Call')
        choices={f:{'action':'accept','expected':v} for f,v in [('title','Suggested sync'),('customer','Acme')]}
        result=c.run(self.db,{'action':'review_recommendations','meeting_id':'m','decisions':choices})
        self.assertEqual(result['meeting_title'],'Suggested sync')
        self.assertEqual(result['manual_companies'],['Acme'])
        result=c.run(self.db,{'action':'review_recommendations','meeting_id':'m','decisions':{f:{**v,'action':'dismiss'} for f,v in choices.items()}})
        self.assertEqual(result['meeting_title'],'Suggested sync');self.assertEqual(result['manual_companies'],['Acme'])
    def test_calendar_candidate_fallback_and_stale_choice_rejected(self):
        result=c.run(self.db,{'action':'save','meeting_id':'m','status':'needs_review','data':{'calendar_source':{'candidate_title':'Placeholder sync'}}})
        self.assertEqual(result['recommendations']['title']['value'],'Placeholder sync')
        self.assertNotIn('customer',result['recommendations'])
        with self.assertRaisesRegex(ValueError,'changed'):
            c.run(self.db,{'action':'review_recommendations','meeting_id':'m','decisions':{'title':{'action':'accept','expected':'Old candidate'}}})


    def test_meet_roster_is_additive_and_survives_calendar_enrichment(self):
        def bridge(names):return c.run(self.db,{'action':'bridge','meeting_id':'m','data':{'meet_title':'Design sync','participants':[{'name':n,'attendance':'confirmed'} for n in names]}})
        bridge(['Ian','Will','Vijay']);result=bridge(['Ian','Vijay','Madhvendra'])
        self.assertEqual([p['name'] for p in result['participants']],['Ian','Will','Vijay','Madhvendra'])
        result=c.run(self.db,{'action':'save','meeting_id':'m','data':{'calendar_title':'Design sync','participants':[{'name':'Ian','email':'ian@hunters.ai'}]}})
        self.assertEqual(len(result['participants']),4);self.assertEqual(result['confirmed_participants'],4)
        self.assertEqual(result['participants'][0]['email'],'ian@hunters.ai')
    def test_meet_title_preserves_manual_names_and_delayed_queue_is_visible(self):
        self.db.execute("UPDATE meetings SET title='My title',title_source='manual'")
        c.run(self.db,{'action':'bridge','meeting_id':'m','data':{'meet_title':'Meet title'}})
        self.assertEqual(c.run(self.db,{'action':'get','meeting_id':'m'})['meeting_title'],'My title')
        c.run(self.db,{'action':'queue','meeting_id':'m'})
        self.db.execute("UPDATE meeting_context SET updated_at=datetime('now','-2 minutes')")
        self.assertTrue(c.run(self.db,{'action':'get','meeting_id':'m'})['queue_delayed'])
    def test_exact_room_cache_returns_review_instead_of_requeue(self):
        c.run(self.db,{'action':'save','meeting_id':'m','data':{'meet_url':'https://meet.google.com/abc-defg-hij','calendar_title':'Weekly planning'}})
        result=c.run(self.db,{'action':'queue','meeting_id':'m'})
        self.assertEqual(result['status'],'needs_review');self.assertEqual(result['recommendations']['title']['value'],'Weekly planning')

    def test_manual_calendar_request_precedes_the_older_backlog(self):
        self.db.execute("INSERT INTO meetings(id,title,created_at) VALUES('older','Old','2025-01-01')")
        self.db.execute("INSERT INTO meeting_context(meeting_id) VALUES('older')")
        c.run(self.db,{'action':'queue','meeting_id':'m'})
        self.assertEqual(c.run(self.db,{'action':'pending'})[0]['id'],'m')
if __name__=='__main__':unittest.main()
