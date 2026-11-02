const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('../../frontend/node_modules/typescript');
const source=fs.readFileSync(path.join(__dirname,'../../frontend/src/lib/speaker-labels.ts'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const context={exports:{}};vm.runInNewContext(compiled,context);
const label=context.exports.speakerLabel;
const data={speakers:[{id:'0',name:'Alice'},{id:'1',name:'Bob'}],segments:[{start:0,end:5,speaker:'0'},{start:5,end:10,speaker:'1'}]};
test('speaker turn labels use audio-relative time',()=>{assert.equal(label(data,1,3),'Alice');assert.equal(label(data,6,9),'Bob');});
test('chunks spanning two voices retain both names',()=>{assert.equal(label(data,4,6),'Alice / Bob');});
test('silence and missing timestamps do not invent an identity',()=>{assert.equal(label(data,11,12),undefined);assert.equal(label(data,NaN,12),undefined);assert.equal(label(null,1,2),undefined);});
test('small boundary spill does not mislabel a whole chunk',()=>{assert.equal(label(data,1,5.01),'Alice');});

test('unreliable over-clustered analyses do not attribute transcript text',()=>{assert.equal(label({...data,analysis_warning:'111 groups'},1,3),undefined);});
