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
 def test_empty_cached_result_is_reanalyzed_and_labels_survive_reopen(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as directory:
   base={'root':directory,'meeting_id':'saved-meeting'}
   empty={'model':worker.MODEL_ID,'segments':[],'speakers':[]}
   voice={'model':worker.MODEL_ID,'segments':[{'start':0.,'end':12.,'speaker':'0'}],
          'speakers':[{'id':'0','name':'Speaker 1','embedding':[1.,0.],'clean_seconds':12.,'profile_id':None,'status':'unknown'}]}
   with patch.object(worker,'analyze',return_value=empty):worker.run(dict(base,action='analyze'))
   with patch.object(worker,'analyze',return_value=voice) as analyze:
    worker.run(dict(base,action='analyze'));analyze.assert_called_once()
   worker.run(dict(base,action='label',speaker_id='0',name='Saved name'))
   self.assertEqual(worker.run(dict(base,action='get'))['speakers'][0]['name'],'Saved name')

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

 def test_excessive_clusters_rejected_in_auto_and_fixed_modes(self):
  turns=[{'speaker':str(i),'start':float(i),'end':float(i+1)} for i in range(111)]
  for count in [-1,8]:
   with self.assertRaisesRegex(ValueError,'111 groups'):worker.validate_turn_count(turns,count)
  self.assertEqual(worker.validate_turn_count(turns[:8],8),8)
  self.assertEqual(worker.validate_turn_count(turns[:6],8),6)

 def test_legacy_111_cluster_result_cannot_enroll_and_count_change_bypasses_cache(self):
  with tempfile.TemporaryDirectory() as temp:
   base={'root':temp,'meeting_id':'broken'}
   worker.run(dict(base,action='get'))
   broken={'model':worker.MODEL_ID,'segments':[{'speaker':str(i),'start':float(i),'end':float(i+1)} for i in range(111)],'speakers':[{'id':str(i),'embedding':[1.,0.],'clean_seconds':20.,'name':'Speaker '+str(i)} for i in range(111)]}
   key=worker.hashlib.sha256(b'broken').hexdigest()
   with sqlite3.connect(Path(temp)/'voices.sqlite') as db:db.execute('INSERT INTO meetings VALUES (?,?)',(key,json.dumps(broken)))
   visible=worker.run(dict(base,action='get'))
   self.assertIn('111 groups',visible['analysis_warning'])
   self.assertTrue(all(not s['can_enroll'] for s in visible['speakers']))
   with self.assertRaisesRegex(ValueError,'unreliable'):worker.run(dict(base,action='enroll',speaker_id='0',name='Alice'))
   with self.assertRaisesRegex(ValueError,'known speaker count'):worker.run(dict(base,action='analyze'))
   repaired={'model':worker.MODEL_ID,'segments':broken['segments'][:8],'speakers':broken['speakers'][:8]}
   with patch.object(worker,'analyze',return_value=repaired) as analyze:
    result=worker.run(dict(base,action='analyze',num_speakers=8))
    analyze.assert_called_once()
   self.assertEqual(len(result['speakers']),8)
   self.assertIsNone(result['analysis_warning'])
   with patch.object(worker,'analyze') as analyze:
    worker.run(dict(base,action='analyze',num_speakers=8));analyze.assert_not_called()

 def test_failed_reanalysis_preserves_previous_analysis(self):
  with tempfile.TemporaryDirectory() as temp:
   base={'root':temp,'meeting_id':'keep'}
   valid={'model':worker.MODEL_ID,'segments':[],'speakers':[]}
   with patch.object(worker,'analyze',return_value=valid):worker.run(dict(base,action='analyze',num_speakers=8))
   invalid={'model':worker.MODEL_ID,'segments':[{'speaker':str(i)} for i in range(111)],'speakers':[]}
   with patch.object(worker,'analyze',return_value=invalid):
    with self.assertRaisesRegex(ValueError,'111 groups'):worker.run(dict(base,action='analyze',num_speakers=8,force=True))
   self.assertEqual(worker.run(dict(base,action='get'))['speakers'],[])

 def test_count_validation(self):
  self.assertEqual(worker.requested_count({'num_speakers':8}),8)
  for value in [0,21,8.5,True,'8',None]:
   with self.assertRaises(ValueError):worker.requested_count({'num_speakers':value})

 def test_global_clustering_consolidates_111_fragments_without_turning_noise_into_people(self):
  import numpy as np
  speakers=[];turns=[]
  for i in range(111):
   vector=np.eye(8)[i%8].tolist()
   speakers.append({'id':str(i),'embedding':vector,'mixed':False,'clean_seconds':12.,'sample_path':None})
   turns.append({'speaker':str(i),'start':float(i*13),'end':float(i*13+12)})
  speakers.append({'id':'noise','embedding':None,'mixed':False,'clean_seconds':.4})
  turns.append({'speaker':'noise','start':1500.,'end':1500.4})
  result=worker.consolidate_fragments({'speakers':speakers,'segments':turns},8)
  self.assertEqual(len(result['speakers']),8)
  self.assertEqual(worker.validate_turn_count(result['segments'],8),8)
  self.assertEqual(result['segments'][-1]['speaker'],'__unassigned__')
  self.assertGreater(result['unassigned_seconds'],0)
  self.assertTrue(all(s['clean_seconds']>=120 for s in result['speakers']))

 def test_too_few_reliable_fragments_does_not_fabricate_speakers(self):
  result={'speakers':[{'id':'0','embedding':[1.,0.],'mixed':False,'clean_seconds':20.}],'segments':[]}
  with self.assertRaisesRegex(ValueError,'Only 1 reliable'):worker.consolidate_fragments(result,8)

if __name__=='__main__':unittest.main()
