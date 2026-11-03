import importlib.util,sqlite3,tempfile,unittest,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('exporter',Path(__file__).with_name('export_portal.py'));e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
class ExportTests(unittest.TestCase):
 def test_title_selection(self):
  raw={'english_cache':{'markdown':'# Snowflake Connector Partnership\n\nSummary text'}}
  self.assertEqual(e.summary_title('Meeting 02_11_26_13_00_45',raw),'Snowflake Connector Partnership')
  self.assertEqual(e.summary_title('My chosen title',raw),'My chosen title')
  self.assertIsNone(e.summary_title('Meeting 02_11_26_13_00_45',{'markdown':'# Meeting Summary\nBody'}))
 def test_wait_for_summary_then_publish(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'meeting.sqlite'
   with sqlite3.connect(path) as db:
    db.executescript('CREATE TABLE meetings(id,title,created_at,folder_path);CREATE TABLE transcripts(meeting_id,transcript,audio_start_time,audio_end_time,timestamp);CREATE TABLE meeting_notes(meeting_id,notes_markdown);CREATE TABLE summary_processes(meeting_id,result,status);CREATE TABLE meeting_context(meeting_id,data);')
    db.execute("INSERT INTO meetings VALUES('m','Meeting 02_11_26_13_00_45','2026-11-02T21:12:40Z','x_2026-11-02_21-00')")
    db.execute("INSERT INTO transcripts VALUES('m','I will follow up.',0,2,'2026-11-02')")
    db.execute("INSERT INTO summary_processes VALUES('m',NULL,'processing')")
   pending=e.export(path);self.assertEqual(pending['meetings'],[]);self.assertEqual(len(pending['pending_summaries']),1)
   with sqlite3.connect(path) as db:db.execute('UPDATE summary_processes SET status=?,result=?',('completed',json.dumps({'markdown':'Summary body','english_cache':{'markdown':'# Snowflake Partnership\nSummary body'}})))
   ready=e.export(path);self.assertEqual(ready['meetings'][0]['title'],'Snowflake Partnership');self.assertEqual(ready['pending_summaries'],[])
 def test_manifest_exported_at_and_duration(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'meeting.sqlite'
   with sqlite3.connect(path) as db:
    db.executescript('CREATE TABLE meetings(id,title,created_at,folder_path);CREATE TABLE transcripts(meeting_id,transcript,audio_start_time,audio_end_time,timestamp);CREATE TABLE meeting_notes(meeting_id,notes_markdown);CREATE TABLE summary_processes(meeting_id,result,status);CREATE TABLE meeting_context(meeting_id,data);')
    db.execute("INSERT INTO meetings VALUES('m','My standup','2026-11-02T21:12:40Z','x_2026-11-02_21-00')")
    db.execute("INSERT INTO meetings VALUES('pending','Meeting 02_11_26_13_00_45','2026-11-02T22:12:40Z','x_2026-11-02_22-00')")
    db.execute("INSERT INTO transcripts VALUES('m','First.',0,2,'2026-11-02')")
    db.execute("INSERT INTO transcripts VALUES('m','Last.',130,185.5,'2026-11-02')")
    db.execute("INSERT INTO summary_processes VALUES('m',NULL,'completed')")
    db.execute("INSERT INTO meeting_notes VALUES('m','# Notes')")
    db.execute("INSERT INTO summary_processes VALUES('pending',NULL,'processing')")
   batch=e.export(path)
   # Manifest lists every local meeting, even the unpublished one.
   self.assertEqual(batch['manifest'],['m','pending'])
   self.assertTrue(batch['exported_at'])
   self.assertEqual(batch['meetings'][0]['duration_seconds'],185.5)
   # A --meeting-id filter narrows the export but never the manifest.
   filtered=e.export(path,['m'])
   self.assertEqual(filtered['manifest'],['m','pending'])
   self.assertEqual([m['id'] for m in filtered['meetings']],['m'])
 def test_db_path_with_spaces_opens(self):
  # The default Meetily DB lives under "Application Support" - a path with a
  # space. Regression test for the file: URI failure on such paths.
  with tempfile.TemporaryDirectory(prefix='space dir ') as tmp:
   path=Path(tmp)/'meeting.sqlite'
   with sqlite3.connect(path) as db:
    db.executescript('CREATE TABLE meetings(id,title,created_at,folder_path);CREATE TABLE transcripts(meeting_id,transcript,audio_start_time,audio_end_time,timestamp);CREATE TABLE meeting_notes(meeting_id,notes_markdown);CREATE TABLE summary_processes(meeting_id,result,status);CREATE TABLE meeting_context(meeting_id,data);')
    db.execute("INSERT INTO meetings VALUES('m','My standup','2026-11-02T21:12:40Z',NULL)")
    db.execute("INSERT INTO summary_processes VALUES('m',NULL,'processing')")
   batch=e.export(path)
   self.assertEqual(batch['manifest'],['m'])
 def test_oversized_fields_are_truncated_with_warning(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'meeting.sqlite'
   with sqlite3.connect(path) as db:
    db.executescript('CREATE TABLE meetings(id,title,created_at,folder_path);CREATE TABLE transcripts(meeting_id,transcript,audio_start_time,audio_end_time,timestamp);CREATE TABLE meeting_notes(meeting_id,notes_markdown);CREATE TABLE summary_processes(meeting_id,result,status);CREATE TABLE meeting_context(meeting_id,data);')
    db.execute("INSERT INTO meetings VALUES('m','Long meeting','2026-11-02T21:12:40Z',NULL)")
    db.execute("INSERT INTO transcripts VALUES('m',?,0,2,'2026-11-02')",('x'*600000,))
    db.execute("INSERT INTO summary_processes VALUES('m',NULL,'completed')")
    db.execute("INSERT INTO meeting_notes VALUES('m','# Notes')")
   batch=e.export(path)
   meeting=batch['meetings'][0]
   self.assertLessEqual(len(meeting['transcript']),500000)
   self.assertIn('truncated',meeting['transcript'])
   self.assertEqual(len(batch['warnings']),1)
if __name__=='__main__':unittest.main()
