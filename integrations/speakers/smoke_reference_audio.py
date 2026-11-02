"""Optional network + real-model smoke test using official public reference audio."""
from pathlib import Path
import json,subprocess,sys,urllib.request,shutil
import numpy as np
import soundfile as sf
import tempfile

def main():
 project=Path(__file__).resolve().parents[2]
 with tempfile.TemporaryDirectory(prefix='meetily-reference-') as scratch:
  root=Path(scratch)
  worker=project/'frontend/src-tauri/speaker_runtime/worker.py'
  models=Path.home()/'Library/Application Support/com.meetily.ai/speaker-recognition/models'
  store=root/'known-speaker-store-multilingual-v3';(store/'models').mkdir(parents=True,exist_ok=True)
  for name in ['segmentation.onnx','embedding.onnx']:shutil.copy2(models/name,store/'models'/name)
  cache=root/'speaker-reference';cache.mkdir(exist_ok=True)
  base='https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/'
  sets={'A':{'train':['fangjun-sr-1.wav','fangjun-sr-2.wav','fangjun-sr-3.wav','fangjun-sr-2.wav'],'test':['fangjun-test-sr-1.wav','fangjun-test-sr-2.wav','fangjun-test-sr-1.wav','fangjun-test-sr-2.wav']},'B':{'train':['leijun-sr-1.wav','leijun-sr-2.wav','leijun-sr-2.wav'],'test':['leijun-test-sr-1.wav','leijun-test-sr-2.wav','leijun-test-sr-3.wav']}}
  def call(action,meeting,**extra):
   request=dict(root=str(store),action=action,meeting_id=meeting,ffmpeg=str(project/'frontend/src-tauri/binaries/ffmpeg-aarch64-apple-darwin'),**extra)
   result=subprocess.run([sys.executable,str(worker)],input=json.dumps(request),text=True,capture_output=True,check=True)
   return json.loads(result.stdout)
  for person,kinds in sets.items():
   for kind,names in kinds.items():
    arrays=[]
    for name in names:
     target=cache/name
     if not target.exists():urllib.request.urlretrieve(base+name,target)
     audio,rate=sf.read(target,dtype='float32');arrays.append(audio)
    target=cache/f'{person}-{kind}.wav';sf.write(target,np.concatenate(arrays),rate)
    kinds[kind]=target
  for person,kinds in sets.items():
   result=call('analyze','train-'+person,audio=str(kinds['train']),num_speakers=1)
   print('Training',person,[(s['clean_seconds'],s.get('mixed'))for s in result['speakers']],flush=True)
   result=call('enroll','train-'+person,speaker_id='0',name='Reference '+person)
  for person,kinds in sets.items():
   result=call('analyze','test-'+person,audio=str(kinds['test']),num_speakers=1)
   print('Recognition',person,[(s['name'],s['status'],s['clean_seconds'],s.get('score'),s.get('mixed'))for s in result['speakers']],flush=True)
   assert result['speakers'][0]['name']=='Reference '+person
   assert result['speakers'][0]['status']=='recognized'
  print('Held-out reference voices matched correctly across separate worker processes',flush=True)

if __name__ == "__main__": main()
