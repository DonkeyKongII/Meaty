const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, 'content.js'), 'utf8');
function fixture({label = 'Join now', visible = true, icon = '', count = null, labelledCount = false, pathname = '/abc-defg-hij', stored = new Map()} = {}) {
  let tick, now = 10000;
  const sent = [];
  const button = {getClientRects: () => visible ? [1] : [], getAttribute: name => name === 'aria-label' ? label : '', querySelectorAll: () => [{textContent:icon}]};
  vm.runInNewContext(code, {
    location:{pathname}, document:{getElementById:id=>id==='people-label'?{textContent:'People'}:null,querySelectorAll:selector => selector.includes('data-participant-count') ? (count===null?[]:[{getClientRects:()=>[1],getAttribute:name=>name===(labelledCount?'aria-labelledby':'data-participant-count')?(labelledCount?'people-label':String(count)):'',textContent:labelledCount?'People'+count:''}]) : [button]}, getComputedStyle:() => ({visibility:'visible'}),
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
test('instant meeting /meet/code URLs trigger only after joining', async () => {
  const preview=fixture({pathname:'/meet/ayq-dxzm-dqu'});await preview.tick();assert.equal(preview.sent.length,0);
  const joined=fixture({pathname:'/meet/ayq-dxzm-dqu',label:'Leave call'});await joined.tick();assert.ok(joined.sent.length);
  const ended=fixture({pathname:'/meet/ayq-dxzm-dqu',label:'Rejoin'});await ended.tick();assert.equal(ended.sent.length,0);
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
  let listener, removed, updated, calls=0;
  const messages=[];
  const local={enabled}, session={};
  const storage=data=>({
    async get(key) { if(key===null)return {...data}; return {[key]:data[key]}; },
    async set(values){Object.assign(data,values);}, async remove(keys){keys.forEach(key=>delete data[key]);},
  });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'background.js'),'utf8'),{
    chrome:{runtime:{onMessage:{addListener:fn=>listener=fn},async sendNativeMessage(host,message){calls++;messages.push(message);if(fail)throw Error('Host unavailable');return {accepted:true};}},
      storage:{local:storage(local),session:storage(session)},tabs:{onRemoved:{addListener:fn=>removed=fn},onUpdated:{addListener:fn=>updated=fn}}},
  });
  return {messages, close: id=>removed(id), navigate: (id,url)=>updated(id,{url}), get calls(){return calls;},setFail(value){fail=value;},send(sender={tab:{id:1},url:'https://meet.google.com/abc-defg-hij'},event='joined',count=null) {
    return new Promise(resolve=>{const result=listener({event,provider:'google-meet',session:'same-call',participant_count:count},sender,resolve);if(!result)resolve(undefined);});
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

test('leaving sends ended with the original call session',async()=>{
 const f=fixture({label:'Leave call'});await f.tick();const session=f.sent[0].session;
 f.setLabel('Rejoin');await f.tick();assert.equal(f.sent.at(-1).event,'ended');assert.equal(f.sent.at(-1).session,session);
});
test('closing a joined tab delivers end and clears deduplication',async()=>{
 const w=worker();await w.send();await w.close(1);
 assert.equal(w.messages.at(-1).event,'ended');await w.send();assert.equal(w.calls,3);
});
test('ended then same-session reconnect is forwarded to cancel grace',async()=>{
 const w=worker();await w.send();await w.send(undefined,'ended');await w.send();
 assert.deepEqual(w.messages.map(m=>m.event),['joined','ended','joined']);
});
test('closing an unrelated tab does not end the active meeting',async()=>{
 const w=worker();await w.send();await w.close(2);assert.equal(w.calls,1);
});

test('duplicated tabs receive distinct native session identities',async()=>{
 const w=worker();await w.send();await w.send({tab:{id:2},url:'https://meet.google.com/abc-defg-hij'});
 assert.notEqual(w.messages[0].session,w.messages[1].session);
 await w.close(1);assert.equal(w.messages.at(-1).session,w.messages[0].session);
});

test('joined heartbeat samples explicit participant counts including self', async()=>{
 const f=fixture({label:'Leave call',count:8}); await f.tick();assert.equal(f.sent.at(-1).participant_count,8);
});
test('participant updates keep accepted ownership and tab-close stop behavior',async()=>{
 const f=worker();await f.send();await f.send(undefined,'joined',8);await f.send(undefined,'joined',3);
 assert.equal(f.messages[1].event,'participants');assert.equal(f.messages[1].participant_count,8);
 assert.equal(f.messages[2].event,'participants');await f.close(1);assert.equal(f.messages.at(-1).event,'ended');
});
test('invalid counts do not create participant events',async()=>{
 const f=worker();await f.send();await f.send(undefined,'joined',999);assert.equal(f.calls,1);
});

test('Google Meet People badge uses aria-labelledby and concatenated text',async()=>{const f=fixture({label:'Leave call',count:7,labelledCount:true});await f.tick();assert.equal(f.sent.at(-1).participant_count,7);});
