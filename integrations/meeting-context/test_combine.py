import importlib.util,json,sqlite3,tempfile,unittest,wave,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'frontend/src-tauri/context_runtime'))
from context import run
FFMPEG=ROOT/'target/release/bundle/macos/meetily.app/Contents/MacOS/ffmpeg'
class CombineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.executescript('CREATE TABLE meetings(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,updated_at TEXT,folder_path TEXT);CREATE TABLE transcripts(id TEXT PRIMARY KEY,meeting_id TEXT REFERENCES meetings(id),transcript TEXT,timestamp TEXT,audio_start_time REAL,audio_end_time REAL,duration REAL);CREATE TABLE meeting_notes(meeting_id TEXT PRIMARY KEY,notes_markdown TEXT,created_at TEXT,updated_at TEXT);')
  self.db.executescript((ROOT/'frontend/src-tauri/migrations/20261102000000_meeting_context.sql').read_text())
  for i,rate in [(1,16000),(2,48000)]:
   folder=self.base/str(i);folder.mkdir()
   with wave.open(str(folder/'audio.wav'),'wb') as w:w.setparams((1,2,rate,0,'NONE','not compressed'));w.writeframes(b'\x00\x01'*rate*i)
   (folder/'metadata.json').write_text(json.dumps({'status':'completed','duration_seconds':i,'created_at':f'2026-11-02T20:0{i}:00Z'}))
   self.db.execute('INSERT INTO meetings VALUES(?,?,?,?,?)',(str(i),'Part '+str(i),'2026-11-02T20:00:00Z','2026-11-02T20:00:00Z',str(folder)))
   self.db.execute('INSERT INTO transcripts VALUES(?,?,?,?,?,?,?)',('t'+str(i),str(i),'Words '+str(i),'20:00:00',0.1,i-0.1,i-0.2))
   self.db.execute('INSERT INTO meeting_notes VALUES(?,?,?,?)',(str(i),'Note '+str(i),'now','now'))
   run(self.db,{'action':'save','meeting_id':str(i),'data':{'participants':[{'name':'Ian','email':'ian@hunters.ai','attendance':'confirmed'}],'manual_companies':['Internal']}})
  self.request={'action':'combine','meeting_ids':['1','2'],'title':'Combined call','include_audio':True,'ffmpeg_path':str(FFMPEG)}
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_audio_timeline_notes_and_originals(self):
  before=[(p,p.read_bytes()) for p in self.base.glob('*/*')]
  result=run(self.db,{**self.request,'meeting_ids':['2','1']});mid=result['id'];folder=Path(result['folder_path'])
  with wave.open(str(folder/'audio.wav')) as w:self.assertEqual(w.getnframes(),48000*3)
  rows=self.db.execute('SELECT * FROM transcripts WHERE meeting_id=? ORDER BY audio_start_time',(mid,)).fetchall()
  self.assertEqual([r['transcript'] for r in rows],['Words 1','Words 2']);self.assertAlmostEqual(rows[1]['audio_start_time'],1.1)
  self.assertEqual(self.db.execute('SELECT count(*) FROM meetings').fetchone()[0],3)
  for p,content in before:self.assertEqual(p.read_bytes(),content)
  context=run(self.db,{'action':'get','meeting_id':mid});self.assertEqual(context['classification'],'internal');self.assertEqual(context['confirmed_participants'],1)
  self.assertEqual(len(context['combined_from']),2)
  notes=self.db.execute('SELECT notes_markdown FROM meeting_notes WHERE meeting_id=?',(mid,)).fetchone()[0];self.assertIn('Note 1',notes);self.assertIn('Note 2',notes)
  self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='profiles'").fetchone())
 def test_transcript_only_ignores_requested_order(self):
  result=run(self.db,{**self.request,'meeting_ids':['2','1'],'include_audio':False});mid=result['id']
  rows=self.db.execute('SELECT transcript,audio_start_time FROM transcripts WHERE meeting_id=? ORDER BY audio_start_time',(mid,)).fetchall();self.assertEqual(rows[0][0],'Words 1');self.assertAlmostEqual(rows[1][1],1.1)
  self.assertFalse((Path(result['folder_path'])/'audio.wav').exists())
 def test_failure_rolls_back_files_and_database(self):
  self.db.execute("CREATE TRIGGER reject_combined BEFORE INSERT ON meetings WHEN NEW.title='Combined call' BEGIN SELECT RAISE(ABORT,'test failure'); END")
  with self.assertRaises(sqlite3.IntegrityError):run(self.db,self.request)
  self.assertEqual(list(self.base.glob('Combined_*')),[]);self.assertEqual(self.db.execute('SELECT count(*) FROM meetings').fetchone()[0],2)
 def test_missing_audio_and_duplicate_selection_rejected(self):
  with self.assertRaises(ValueError):run(self.db,{**self.request,'meeting_ids':['1','1']})
  (self.base/'2/audio.wav').unlink()
  with self.assertRaisesRegex(ValueError,'Missing audio'):run(self.db,self.request)
  self.assertEqual(list(self.base.glob('Combined_*')),[])
 def test_cannot_combine_a_recording_with_a_copy_that_already_contains_it(self):
  result=run(self.db,{**self.request,'include_audio':False})
  with self.assertRaisesRegex(ValueError,'overlapping'):
   run(self.db,{**self.request,'meeting_ids':['1',result['id']],'include_audio':False})
 def test_unknown_source_roster_does_not_become_internal(self):
  run(self.db,{'action':'save','meeting_id':'2','data':{'participants':[],'manual_companies':[]}})
  result=run(self.db,{**self.request,'include_audio':False})
  self.assertEqual(run(self.db,{'action':'get','meeting_id':result['id']})['classification'],'unknown')
 def test_start_time_beats_save_time_and_respects_timezone(self):
  (self.base/'1/metadata.json').write_text(json.dumps({'status':'completed','duration_seconds':1,'created_at':'2026-11-02T23:00:00+02:00'}))
  (self.base/'2/metadata.json').write_text(json.dumps({'status':'completed','duration_seconds':2,'created_at':'2026-11-02T20:30:00Z'}))
  self.db.execute("UPDATE meetings SET created_at='2026-11-02T20:00:00Z' WHERE id='1'")
  rows=run(self.db,{'action':'candidates'});self.assertEqual([r['id'] for r in rows],['2','1'])
  result=run(self.db,{**self.request,'include_audio':False})
  context=run(self.db,{'action':'get','meeting_id':result['id']})
  self.assertEqual([p['meeting_id'] for p in context['combined_from']],['2','1'])
  self.assertEqual(context['recording_started_at'],'2026-11-02T20:30:00+00:00')
 def test_folder_start_fallback(self):
  folder=self.base/'Part_2026-11-02_19-00';folder.mkdir()
  self.db.execute('UPDATE meetings SET folder_path=? WHERE id=?',(str(folder),'2'))
  rows=run(self.db,{'action':'candidates'});self.assertEqual(rows[0]['id'],'2')
  self.assertEqual(rows[0]['started_at'],'2026-11-02T19:00:00+00:00')
 def test_active_source_rejected(self):
  (self.base/'2/metadata.json').write_text('{"status":"recording"}')
  with self.assertRaisesRegex(ValueError,'Finish recording'):run(self.db,self.request)
if __name__=='__main__':unittest.main()
