#!/usr/bin/env python3
"""Install the offline macOS speaker runtime without changing system Python."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import venv

ASSETS = {
 'segmentation.tar.bz2': ('https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2','24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488'),
 'embedding.onnx': ('https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx','aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2'),
}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path);args=parser.parse_args()
 root=Path.home()/'Library/Application Support/com.meetily.ai/speaker-recognition'
 root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
 environment=root/'venv'
 if not (environment/'bin/python3').is_file(): venv.EnvBuilder(with_pip=True).create(environment)
 subprocess.run([str(environment/'bin/python3'),'-m','pip','install','sherpa-onnx==2.0.1','numpy==1.26.4','scipy==1.13.1','soundfile==0.13.1'],check=True)
 models=root/'models';models.mkdir(exist_ok=True)
 for name,(url,checksum) in ASSETS.items():
  target=models/name
  if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=checksum:
   staged=models/(name+'.download')
   if args.cache and (args.cache/name).is_file(): shutil.copy2(args.cache/name,staged)
   else: urllib.request.urlretrieve(url,staged)
   if hashlib.sha256(staged.read_bytes()).hexdigest()!=checksum: raise RuntimeError('Model checksum mismatch: '+name)
   staged.replace(target)
 with tarfile.open(models/'segmentation.tar.bz2') as archive:
  for basename in ['model.onnx','LICENSE','README.md']:
   member=next(item for item in archive.getmembers() if item.name.endswith('/'+basename))
   destination=models/('segmentation.onnx' if basename=='model.onnx' else 'segmentation-'+basename)
   destination.write_bytes(archive.extractfile(member).read())
 print('Offline speaker runtime ready at '+str(root))

if __name__=='__main__':main()
