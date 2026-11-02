import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('worker',Path(__file__).resolve().parents[2]/'frontend/src-tauri/speaker_runtime/worker.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class SpeakerTests(unittest.TestCase):
 def test_match_requires_threshold_and_separation(self):
  profiles=[{'id':'a','name':'A','embedding':[1.,0.]},{'id':'b','name':'B','embedding':[0.,1.]}]
  self.assertEqual(worker.match_voice([1.,.1],profiles)[0]['id'],'a')
  self.assertIsNone(worker.match_voice([1.,1.],profiles)[0])
  self.assertIsNone(worker.match_voice([-1.,-1.],profiles)[0])
  self.assertIsNone(worker.match_voice([float('nan'),0.],profiles)[0])
  self.assertIsNone(worker.match_voice([0.,0.],profiles)[0])
  self.assertIsNone(worker.match_voice([1.,0.,0.],profiles)[0])

 def test_overlap_excluded_from_enrollment(self):
  first={'start':0.,'end':10.,'speaker':'0'};second={'start':3.,'end':6.,'speaker':'1'}
  self.assertEqual(worker.clean_intervals(first,[first,second]),[(.1,2.9),(6.1,9.9)])

 def test_profiles_persist_rename_and_delete_and_never_implicitly_learn(self):
  with tempfile.TemporaryDirectory() as temp:
   base={'root':temp,'meeting_id':'m'}
   result={'model':worker.MODEL_ID,'segments':[{'start':0.,'end':12.,'speaker':'0'}], 'speakers':[{'id':'0','name':'Speaker 1','embedding':[1.,0.],'clean_seconds':12.,'sample_path':None,'profile_id':None,'status':'unknown','score':None}]}
   with patch.object(worker,'analyze',return_value=json.loads(json.dumps(result))):
    initial=worker.run(dict(base,action='analyze'))
   self.assertEqual(initial['profiles'],[])
   self.assertNotIn('embedding',initial['speakers'][0])
   enrolled=worker.run(dict(base,action='enroll',speaker_id='0',name='Alice'))
   profile_id=enrolled['profiles'][0]['id']
   self.assertEqual(worker.run(dict(base,action='get'))['profiles'][0]['name'],'Alice')
   with patch.object(worker,'analyze',return_value=json.loads(json.dumps(result))):
    future=worker.run(dict(base,meeting_id='next-meeting',action='analyze'))
   self.assertEqual(future['speakers'][0]['name'],'Alice')
   self.assertEqual(future['speakers'][0]['status'],'recognized')
   renamed=worker.run(dict(base,action='rename',profile_id=profile_id,name='Alicia'))
   self.assertEqual(renamed['speakers'][0]['name'],'Alicia')
   removed=worker.run(dict(base,action='forget',profile_id=profile_id))
   self.assertEqual(removed['profiles'],[])
   with sqlite3.connect(Path(temp)/'voices.sqlite') as db:self.assertEqual(db.execute('SELECT count(*) FROM profiles').fetchone()[0],0)

 def test_short_sample_can_be_named_but_not_enrolled(self):
  with tempfile.TemporaryDirectory() as temp:
   base={'root':temp,'meeting_id':'short'}
   sample={'model':worker.MODEL_ID,'segments':[], 'speakers':[{'id':'0','embedding':[1.,0.],'clean_seconds':3.,'name':'Speaker 1'}]}
   with patch.object(worker,'analyze',return_value=sample):worker.run(dict(base,action='analyze'))
   with self.assertRaisesRegex(ValueError,'eight seconds'):worker.run(dict(base,action='enroll',speaker_id='0',name='Alice'))
   self.assertEqual(worker.run(dict(base,action='label',speaker_id='0',name='Alice'))['speakers'][0]['name'],'Alice')

 def test_mixed_group_cannot_be_enrolled(self):
  with tempfile.TemporaryDirectory() as temp:
   base={'root':temp,'meeting_id':'mixed'}
   sample={'model':worker.MODEL_ID,'segments':[], 'speakers':[{'id':'0','embedding':[1.,0.],'mixed':True,'clean_seconds':20.,'name':'Speaker 1','status':'unknown'}]}
   with patch.object(worker,'analyze',return_value=sample):result=worker.run(dict(base,action='analyze'))
   self.assertFalse(result['speakers'][0]['can_enroll'])
   with self.assertRaisesRegex(ValueError,'mix voices'):worker.run(dict(base,action='enroll',speaker_id='0',name='Alice'))

if __name__=='__main__':unittest.main()
