from test_worker import worker
import hashlib,json,sqlite3,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
class AssignmentTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=self.temp.name
 def tearDown(self):self.temp.cleanup()
 def call(self,action,meeting='one',**args):return worker.run(dict(root=self.root,meeting_id=meeting,action=action,**args))
 def analyze(self,meeting='one',vector=None,seconds=12,mixed=False):
  result={'model':worker.MODEL_ID,'segments':[{'start':0.,'end':12.,'speaker':'0'},{'start':20.,'end':30.,'speaker':'0'}],'speakers':[{'id':'0','name':'Speaker 1','embedding':vector or [1.,0.],'mixed':mixed,'clean_seconds':seconds,'sample_path':None,'profile_id':None,'status':'unknown'}]}
  with patch.object(worker,'analyze',return_value=result):return self.call('analyze',meeting)
 def samples(self):
  with sqlite3.connect(Path(self.root)/'voices.sqlite') as db:return db.execute('select count(*) from profile_samples').fetchone()[0]
 def test_confirmation_adds_exemplars_and_repeated_save_is_idempotent(self):
  self.analyze();a=self.call('assign',speaker_id='0',name='Alice',remember=True);pid=a['speakers'][0]['profile_id'];self.assertTrue(pid)
  self.analyze('two',[.7,.7]);self.call('assign','two',speaker_id='0',profile_id=pid,name='Alice',remember=True)
  self.assertEqual(self.samples(),2)
  self.call('assign','two',speaker_id='0',profile_id=pid,name='Alice',remember=True);self.assertEqual(self.samples(),2)
  future=self.analyze('three',[.7,.7]);self.assertEqual(future['speakers'][0]['profile_id'],pid);self.assertEqual(self.samples(),2)
  saved=self.call('get','two');self.assertEqual([t['speaker'] for t in saved['segments']],['0','0']);self.assertEqual(saved['speakers'][0]['name'],'Alice')
 def test_short_or_mixed_confirmation_labels_without_learning(self):
  self.analyze(seconds=2,mixed=True);a=self.call('assign',speaker_id='0',name='Alice',remember=True)
  self.assertEqual(a['speakers'][0]['name'],'Alice');self.assertEqual(self.samples(),0);self.assertIn('too little clean speech',a['learning_notice'])
 def test_unclustered_speech_assigns_only_selected_interval(self):
  self.analyze();before=self.call('get');a=self.call('assign',speaker_id='__span__:2:4',name='Bob',remember=True)
  manual=next(s for s in a['speakers'] if s['name']=='Bob');self.assertIn({'start':2.,'end':4.,'speaker':manual['id']},a['segments']);self.assertIn({'start':20.,'end':30.,'speaker':'0'},a['segments']);self.assertEqual(self.samples(),0)
 def test_profile_search_is_bounded_and_get_does_not_load_directory(self):
  self.call('get')
  with sqlite3.connect(Path(self.root)/'voices.sqlite') as db:
   db.executemany('insert into profiles values(?,?,?,?)',[(str(i),f'Customer {i:04}',worker.MODEL_ID,'[1,0]') for i in range(2500)])
  a=self.call('search',query='Customer',offset=0);b=self.call('search',query='Customer',offset=20)
  self.assertEqual(len(a['items']),20);self.assertTrue(a['has_more']);self.assertFalse({p['id'] for p in a['items']}&{p['id'] for p in b['items']})
  self.assertEqual(self.call('get')['profiles'],[]);self.assertEqual(self.call('get')['profile_count'],2500);self.assertEqual(self.call('search',query='%')['items'],[])
 def test_forget_removes_all_learning_samples(self):
  self.analyze();a=self.call('assign',speaker_id='0',name='Alice');pid=a['speakers'][0]['profile_id'];self.assertEqual(self.samples(),1)
  self.call('forget',profile_id=pid);self.assertEqual(self.samples(),0);self.assertIsNone(self.call('get')['speakers'][0]['profile_id'])

 def test_correction_removes_previous_confirmed_exemplar(self):
  self.analyze();a=self.call('assign',speaker_id='0',name='Wrong name');wrong=a['speakers'][0]['profile_id']
  b=self.call('assign',speaker_id='0',name='Right name');right=b['speakers'][0]['profile_id']
  with sqlite3.connect(Path(self.root)/'voices.sqlite') as db:
   self.assertEqual(db.execute('select count(*) from profile_samples where profile_id=?',(wrong,)).fetchone()[0],0)
  future=self.analyze('next');self.assertEqual(future['speakers'][0]['profile_id'],right)
 def test_name_without_remembering_creates_directory_entry_without_learning(self):
  self.analyze();a=self.call('assign',speaker_id='0',name='Meeting person',remember=False)
  self.assertIsNotNone(a['speakers'][0]['profile_id']);self.assertEqual(self.samples(),0)
  self.assertEqual(self.call('search',query='Meeting person')['items'][0]['name'],'Meeting person')
 def test_reference_storage_is_bounded_per_person(self):
  self.analyze();a=self.call('assign',speaker_id='0',name='Alice');pid=a['speakers'][0]['profile_id']
  for i in range(15):
   self.analyze('m'+str(i));self.call('assign','m'+str(i),speaker_id='0',profile_id=pid,name='Alice')
  self.assertEqual(self.samples(),12)

 def test_manual_assignment_at_requested_count_does_not_create_false_cluster_warning(self):
  self.analyze()
  key=hashlib.sha256(b'one').hexdigest()
  with sqlite3.connect(Path(self.root)/'voices.sqlite') as db:
   result=json.loads(db.execute('select data from meetings where id=?',(key,)).fetchone()[0]);result['requested_speakers']=1
   db.execute('update meetings set data=? where id=?',(json.dumps(result),key))
  for start in [2,5]:
   assigned=self.call('assign',speaker_id=f'__span__:{start}:{start+1}',name='Alice',remember=True)
   self.assertIsNone(assigned['analysis_warning'])
  reopened=self.call('get');self.assertIsNone(reopened['analysis_warning']);self.assertEqual(len(reopened['speakers']),3)
  self.assertEqual(self.samples(),0)
  self.assertEqual(len([s for s in reopened['speakers'] if s['name']=='Alice']),2)

 def test_assignment_matches_other_unknown_voices_without_learning_from_them(self):
  self.analyze()
  key=hashlib.sha256(b'one').hexdigest()
  with sqlite3.connect(Path(self.root)/'voices.sqlite') as db:
   value=json.loads(db.execute('select data from meetings where id=?',(key,)).fetchone()[0])
   extra=dict(value['speakers'][0],id='1',embedding=[.99,.01]);value['speakers'].append(extra)
   db.execute('update meetings set data=? where id=?',(json.dumps(value),key))
  result=self.call('assign',speaker_id='0',name='Alice',remember=True)
  self.assertEqual(result['speakers'][1]['status'],'recognized')
  self.assertEqual(result['speakers'][0]['profile_id'],result['speakers'][1]['profile_id'])
  self.assertEqual(self.samples(),1)

 def test_expected_count_allows_extra_distinct_voices_and_fewer_attendees(self):
  voices=[{'embedding':[1.,0.,0.],'clean_seconds':12},{'embedding':[0.,1.,0.],'clean_seconds':12},{'embedding':[0.,0.,1.],'clean_seconds':12}]
  self.assertEqual(worker.estimate_speaker_count(voices,2),3)
  self.assertEqual(worker.estimate_speaker_count(voices[:1],4),1)
  self.assertEqual(worker.estimate_speaker_count(voices+voices,2),3)

 def test_remove_tag_only_affects_selected_passage_and_requires_known_peer(self):
  self.analyze();self.call('assign',speaker_id='0',name='Alice',remember=False)
  key=hashlib.sha256(b'one').hexdigest()
  with sqlite3.connect(Path(self.root)/'voices.sqlite') as db:
   value=json.loads(db.execute('select data from meetings where id=?',(key,)).fetchone()[0])
   value['speakers'].append(dict(value['speakers'][0],id='1',status='unknown',profile_id=None))
   value['segments'] += [dict(t,speaker='1') for t in value['segments']]
   db.execute('update meetings set data=? where id=?',(json.dumps(value),key))
  removed=self.call('remove_tag',speaker_id=json.dumps({'id':'1','start':0,'end':12}))
  self.assertEqual(removed['speaker_tag_exclusions'],[{'speaker':'1','start':0,'end':12}])
  self.assertEqual(removed['segments'],value['segments'])
  self.assertEqual(len(removed['speakers']),2)
  self.assertEqual(self.call('get')['speaker_tag_exclusions'],removed['speaker_tag_exclusions'])
  with self.assertRaisesRegex(ValueError,'Only unidentified'):
   self.call('remove_tag',speaker_id=json.dumps({'id':'0','start':20,'end':30}))
  with self.assertRaisesRegex(ValueError,'Only unidentified'):
   self.call('remove_tag',speaker_id=json.dumps({'id':'1','start':0,'end':12}))

 def test_live_passage_label_survives_first_and_forced_detection(self):
  self.call('assign',speaker_id='__span__:2:4',name='Ian',remember=False)
  for force in (False,True):
   result={'model':worker.MODEL_ID,'segments':[{'start':0.,'end':12.,'speaker':'0'}],'speakers':[{'id':'0','name':'Unknown','embedding':None,'mixed':False,'clean_seconds':12,'sample_path':None,'profile_id':None,'status':'unknown'}]}
   with patch.object(worker,'analyze',return_value=result):saved=self.call('analyze',force=force)
   named=next(s for s in saved['speakers'] if s['name']=='Ian')
   self.assertIn({'start':2.,'end':4.,'speaker':named['id']},saved['segments'])
   self.assertIn({'start':0.,'end':2.,'speaker':'0'},saved['segments'])
   self.assertIn({'start':4.,'end':12.,'speaker':'0'},saved['segments'])
   self.assertEqual(self.samples(),0)
