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
if __name__=='__main__':unittest.main()
