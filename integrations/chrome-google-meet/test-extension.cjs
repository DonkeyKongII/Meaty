const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, 'content.js'), 'utf8');
function fixture({label = 'Join now', visible = true, icon = '', pathname = '/abc-defg-hij', stored = new Map()} = {}) {
  let tick, now = 10000;
  const sent = [];
  const button = {getClientRects: () => visible ? [1] : [], getAttribute: name => name === 'aria-label' ? label : '', querySelectorAll: () => [{textContent:icon}]};
  vm.runInNewContext(code, {
    location:{pathname}, document:{querySelectorAll:() => [button]}, getComputedStyle:() => ({visibility:'visible'}),
    chrome:{runtime:{sendMessage: async message => {sent.push(message); return {accepted:true};}}},
    sessionStorage:{getItem:key => stored.get(key) || null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)},
    crypto:{randomUUID:() => `session-${now}`}, Date:{now:() => now}, console,
    setInterval:fn => {tick=fn;},
  });
  return {sent, stored, async tick(ms=2000) {now+=ms;tick();await new Promise(resolve => setImmediate(resolve));}, setLabel(value){label=value;}};
}
test('prejoin preview does not trigger recording', async () => {
  const f=fixture();await f.tick();assert.equal(f.sent.length,0);
});
test('visible joined-call control triggers and keeps one session on heartbeats', async () => {
  const f=fixture({label:'Leave call'});await f.tick();await f.tick();
  assert.ok(f.sent.length>=2);assert.equal(new Set(f.sent.map(m=>m.session)).size,1);
});
test('hidden controls and non-meeting URLs do not trigger', async () => {
  for(const options of [{label:'Leave call',visible:false},{label:'Leave call',pathname:'/landing'}]) {
    const f=fixture(options);await f.tick();assert.equal(f.sent.length,0);
  }
});
test('call_end icon supports localized leave controls', async () => {
  const f=fixture({label:'Quitter',icon:'call_end'});await f.tick();assert.ok(f.sent.length);
});
test('page reload keeps session to avoid restart after manual stop', async () => {
  const a=fixture({label:'Leave call'});await a.tick();
  const b=fixture({label:'Leave call',stored:a.stored});await b.tick();
  assert.equal(a.sent[0].session,b.sent[0].session);
});
test('brief UI disappearance preserves session; leaving then rejoining creates a new one', async () => {
  const f=fixture({label:'Leave call'});await f.tick();const first=f.sent[0].session;
  f.setLabel('Join now');await f.tick();f.setLabel('Leave call');await f.tick();assert.equal(f.sent.at(-1).session,first);
  f.setLabel('Join now');await f.tick();await f.tick(6000);f.setLabel('Leave call');await f.tick();assert.notEqual(f.sent.at(-1).session,first);
});
function worker({enabled=true, fail=false}={}) {
  let listener, calls=0;
  const local={enabled}, session={};
  const storage=data=>({
    async get(key) { if(key===null)return {...data}; return {[key]:data[key]}; },
    async set(values){Object.assign(data,values);}, async remove(keys){keys.forEach(key=>delete data[key]);},
  });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'background.js'),'utf8'),{
    chrome:{runtime:{onMessage:{addListener:fn=>listener=fn},async sendNativeMessage(){calls++;if(fail)throw Error('Host unavailable');return {accepted:true};}},
      storage:{local:storage(local),session:storage(session)},tabs:{onRemoved:{addListener(){}}}},
  });
  return {get calls(){return calls;},setFail(value){fail=value;},send(sender={tab:{id:1},url:'https://meet.google.com/abc-defg-hij'}) {
    return new Promise(resolve=>{const result=listener({event:'joined',provider:'google-meet',session:'same-call'},sender,resolve);if(!result)resolve(undefined);});
  }};
}
test('worker sends an accepted session to native host only once',async()=>{
 const w=worker();assert.equal((await w.send()).accepted,true);await w.send();assert.equal(w.calls,1);
});
test('disabled extension never invokes native host',async()=>{
 const w=worker({enabled:false});assert.equal((await w.send()).disabled,true);assert.equal(w.calls,0);
});
test('native failures can retry rather than poisoning session deduplication',async()=>{
 const w=worker({fail:true});assert.equal((await w.send()).accepted,false);w.setFail(false);assert.equal((await w.send()).accepted,true);assert.equal(w.calls,2);
});
test('worker rejects messages from other origins',async()=>{
 const w=worker();assert.equal(await w.send({tab:{id:1},url:'https://example.com/'}),undefined);assert.equal(w.calls,0);
});
