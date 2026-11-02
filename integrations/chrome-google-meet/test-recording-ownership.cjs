const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('../../frontend/node_modules/typescript');
function fixture() {
 const exports={};let fail=false;const data=new Map();
 const source=fs.readFileSync('frontend/src/lib/meeting-recording.ts','utf8');
 vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{
  exports,require:()=>({recordingService:{async startRecordingWithDevices(){if(fail)throw Error('start failed');}}}),
  sessionStorage:{getItem:k=>data.get(k),removeItem:k=>data.delete(k)},
 });
 return {api:exports,data,setFail:v=>fail=v};
}
test('only a successful companion start owns the recording',async()=>{
 const f=fixture();await f.api.startWithOwnership(false,null,null,'manual');assert.equal(f.api.companionOwnsRecording(),false);
 f.setFail(true);await assert.rejects(f.api.startWithOwnership(true,null,null,'auto'));assert.equal(f.api.companionOwnsRecording(),false);
 f.setFail(false);await f.api.startWithOwnership(true,null,null,'auto');assert.equal(f.api.companionOwnsRecording(),true);
 f.api.clearCompanionRecording();assert.equal(f.api.companionOwnsRecording(),false);
 await f.api.startWithOwnership(false,null,null,'later manual');assert.equal(f.api.companionOwnsRecording(),false);
});
test('companion start request is consumed once and cannot leak to later starts',()=>{
 const f=fixture();f.data.set('meetilyCompanionStart','true');assert.equal(f.api.consumeCompanionStart(),true);assert.equal(f.api.consumeCompanionStart(),false);
});
