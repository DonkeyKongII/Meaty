const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const frontend=path.resolve(__dirname,'../../frontend');
const ts=require(path.join(frontend,'node_modules/typescript'));
const React=require(path.join(frontend,'node_modules/react'));
const {create,act}=require(path.join(frontend,'node_modules/react-test-renderer'));
const originalLoad=Module._load;
const calls=[];
const data={model:'test',requested_speakers:-1,segments:[{start:0,end:5,speaker:'1'},{start:5,end:10,speaker:'2'}],speakers:[{id:'1',name:'Ian',profile_id:'ian',status:'manual',sample_path:null},{id:'2',name:'Speaker 2',profile_id:null,status:'unknown',sample_path:null}],profiles:[{id:'ian',name:'Ian'}]};
const invoke=async(command,args)=>{calls.push({command,args});if(command==='speaker_action')return args.action==='search'?{items:[{id:'ian',name:'Ian'}],has_more:false}:data;if(command==='meeting_context_action'&&recommendationFixture){if(args.request.action==='review_recommendations'){for(const [field,choice] of Object.entries(args.request.decisions)){recommendationFixture.recommendations[field].state=choice.action==='accept'?'accepted':'dismissed';}}return structuredClone(recommendationFixture);}if(command==='meeting_context_action')return {calendar_title:'Weekly sync',meeting_title:'Weekly sync',participants:[{name:'Ian'},{name:'Eli'}],status:'complete'};return {};};
let visible;
let recommendationFixture=null;
const listeners=new Map();
global.document={visibilityState:'hidden',addEventListener(){},removeEventListener(){}};
global.window={addEventListener(name,fn){listeners.set(name,fn)},removeEventListener(name){listeners.delete(name)}};
Module._extensions['.tsx']=Module._extensions['.ts']=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020,esModuleInterop:true}}).outputText,file);
const refetchMeetings=async()=>{};
Module._load=function(request,parent,isMain){
 if(request==='@tauri-apps/api/core')return {invoke,convertFileSrc:s=>s};
 if(request==='@tauri-apps/api/event')return {listen:async()=>()=>{}};
 if(request==='@/components/Sidebar/SidebarProvider')return {useSidebar:()=>({refetchMeetings})};
 if(request==='@/components/VirtualizedTranscriptView')return {VirtualizedTranscriptView:props=>{visible=props;return React.createElement('div',{'data-testid':'transcript'});}};
 if(request==='./TranscriptButtonGroup')return {TranscriptButtonGroup:()=>null};
 if(request==='./CombineMeetingsPanel')return {CombineMeetingsPanel:()=>null};
 if(request==='./MeetingPipelineStatus')return {MeetingPipelineStatus:()=>null};
 if(request.startsWith('@/'))return originalLoad.call(this,path.join(frontend,'src',request.slice(2)),parent,isMain);
 return originalLoad.call(this,request,parent,isMain);
};
const {TranscriptPanel}=require(path.join(frontend,'src/components/MeetingDetails/TranscriptPanel.tsx'));
const {ProfileSearch}=require(path.join(frontend,'src/components/MeetingDetails/SpeakerAssignment.tsx'));
test('meeting panel defaults to details, uses calendar count, steps count, filters and opens transcript assignment',async()=>{
 let renderer;
 await act(async()=>{renderer=create(React.createElement(TranscriptPanel,{meetingId:'m',meetingTitle:'Weekly sync',transcripts:[],customPrompt:'',onPromptChange(){},onCopyTranscript(){},onOpenMeetingFolder:async()=>{},isRecording:false,usePagination:true,segments:[{id:'a',timestamp:0,endTime:4,text:'Hello'},{id:'b',timestamp:6,endTime:9,text:'Goodbye'}]}));});
 const root=renderer.root;
 if(process.env.MEATY_REVIEW_DIR){
   const escape=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
   const html=node=>node==null?'':Array.isArray(node)?node.map(html).join(''):typeof node!=='object'?escape(node):'<'+node.type+Object.entries(node.props).filter(([key,value])=>key!=='children'&&key!=='style'&&!key.startsWith('on')&&value!==false&&value!=null).map(([key,value])=>' '+(key==='className'?'class':key)+'="'+escape(value===true?(key.startsWith('aria-')?'true':''):value)+'"').join('')+'>'+html(node.children)+'</'+node.type+'>';
   const dir=process.env.MEATY_REVIEW_DIR;fs.mkdirSync(dir,{recursive:true});
   const cssDir=path.join(frontend,'out/_next/static/css');
   const css=fs.readdirSync(cssDir).map(file=>fs.readFileSync(path.join(cssDir,file),'utf8')).join('\n');
   fs.writeFileSync(path.join(dir,'review.html'),'<!doctype html><meta charset="utf-8"><style>'+css+'</style><main class="meaty-ui" style="width:390px;min-height:760px">'+html(renderer.toJSON())+'</main>');
 }

 assert.equal(root.findByProps({id:'meeting-details-pane'}).props.hidden,false);
 assert.equal(root.findByProps({id:'meeting-transcript-pane'}).props.hidden,true);
 assert.equal(root.findByProps({id:'expected-speakers'}).props.value,'2');
 act(()=>root.findByProps({'aria-label':'Increase expected speakers'}).props.onClick());
 assert.equal(root.findByProps({id:'expected-speakers'}).props.value,'3');
 act(()=>root.findByProps({id:'meeting-transcript-tab'}).props.onClick());
 act(()=>root.findByProps({'aria-label':'Filter by speaker'}).props.onChange({target:{value:'ian'}}));
 assert.equal(visible.segments.length,1);assert.equal(visible.segments[0].id,'a');
 act(()=>root.findByProps({'aria-label':'Filter by speaker'}).props.onChange({target:{value:'unresolved'}}));
 assert.equal(visible.segments[0].id,'b');
 act(()=>visible.onAssignSpeaker({id:'2',name:'Unidentified speaker'}));
 assert.equal(root.findByProps({role:'dialog'}).props['aria-label'],'Assign speaker');
 act(()=>renderer.unmount());
});
test('opening person search does not fetch the saved-speaker directory until a query is entered',async()=>{
 calls.length=0;let renderer;
 await act(async()=>{renderer=create(React.createElement(ProfileSearch,{meetingId:'m',onSelect(){}}));});
 assert.equal(calls.filter(c=>c.command==='speaker_action'&&c.args.action==='search').length,0);
 await act(async()=>{renderer.root.findByProps({'aria-label':'Find a saved speaker'}).props.onChange({target:{value:'Ian'}});});
 await act(async()=>{await new Promise(r=>setTimeout(r,280));});
 assert.equal(calls.filter(c=>c.command==='speaker_action'&&c.args.action==='search').length,1);
 act(()=>renderer.unmount());
});

test('mixed passage offers removal for its unidentified tag and sends a passage-specific request',async()=>{
 let renderer;
 await act(async()=>{renderer=create(React.createElement(TranscriptPanel,{meetingId:'m',meetingTitle:'Weekly sync',transcripts:[],customPrompt:'',onPromptChange(){},onCopyTranscript(){},onOpenMeetingFolder:async()=>{},isRecording:false,usePagination:true,segments:[{id:'mixed',timestamp:0,endTime:10,text:'Both people spoke here'}]}));});
 act(()=>renderer.root.findByProps({id:'meeting-transcript-tab'}).props.onClick());
 const unknown=visible.speakerTags.mixed.find(t=>t.canRemove);
 assert.ok(unknown);act(()=>visible.onAssignSpeaker(unknown));
 const remove=renderer.root.findAllByType('button').find(b=>b.children.includes('Remove speaker from this passage'));
 assert.ok(remove);
 await act(async()=>{await remove.props.onClick();});
 const request=calls.findLast(c=>c.command==='speaker_action'&&c.args.action==='remove_tag');
 assert.deepEqual(JSON.parse(request.args.speakerId),{id:'2',start:0,end:10});
 act(()=>renderer.unmount());
});

test('meeting details restores explicit customer and Internal assignment controls',async()=>{
 const {MeetingContextPanel}=require(path.join(frontend,'src/components/MeetingDetails/MeetingContextPanel.tsx'));
 let renderer;await act(async()=>{renderer=create(React.createElement(MeetingContextPanel,{meetingId:'m'}));});
 act(()=>renderer.root.findByProps({'aria-label':'Edit meeting assignment'}).props.onClick());
 act(()=>renderer.root.findByProps({'aria-label':'Assign meeting to'}).props.onChange({target:{value:'customer'}}));
 act(()=>renderer.root.findByProps({'aria-label':'Customer name'}).props.onChange({target:{value:'Snowflake'}}));
 await act(async()=>{await renderer.root.findAllByType('button').find(b=>b.children.includes('Save assignment')).props.onClick();});
 let request=calls.findLast(c=>c.args?.request?.action==='classify');
 assert.deepEqual(request.args.request.manual_companies,['Snowflake']);
 act(()=>renderer.root.findByProps({'aria-label':'Edit meeting assignment'}).props.onClick());
 act(()=>renderer.root.findByProps({'aria-label':'Assign meeting to'}).props.onChange({target:{value:'internal'}}));
 await act(async()=>{await renderer.root.findAllByType('button').find(b=>b.children.includes('Save assignment')).props.onClick();});
 request=calls.findLast(c=>c.args?.request?.action==='classify');
 assert.deepEqual(request.args.request.manual_companies,['Internal']);
 assert.equal(request.args.request.data,undefined);
 act(()=>renderer.unmount());
});

test('assignment editor stays hidden until requested and cancel discards its draft',async()=>{
 const {MeetingContextPanel}=require(path.join(frontend,'src/components/MeetingDetails/MeetingContextPanel.tsx'));
 let renderer;await act(async()=>{renderer=create(React.createElement(MeetingContextPanel,{meetingId:'m'}));});
 const root=renderer.root;
 assert.equal(root.findAllByProps({'aria-label':'Assign meeting to'}).length,0);
 assert.ok(root.findAllByType('p').some(p=>p.children.includes('Unassigned')));
 act(()=>root.findByProps({'aria-label':'Edit meeting assignment'}).props.onClick());
 act(()=>root.findByProps({'aria-label':'Assign meeting to'}).props.onChange({target:{value:'customer'}}));
 act(()=>root.findByProps({'aria-label':'Customer name'}).props.onChange({target:{value:'Unsaved customer'}}));
 const before=calls.filter(c=>c.args?.request?.action==='classify').length;
 act(()=>root.findAllByType('button').find(b=>b.children.includes('Cancel')).props.onClick());
 assert.equal(root.findAllByProps({'aria-label':'Assign meeting to'}).length,0);
 assert.equal(calls.filter(c=>c.args?.request?.action==='classify').length,before);
 act(()=>root.findByProps({'aria-label':'Edit meeting assignment'}).props.onClick());
 assert.equal(root.findByProps({'aria-label':'Assign meeting to'}).props.value,'automatic');
 act(()=>renderer.unmount());
});

test('calendar suggestions have independent and combined accept/dismiss controls',async()=>{
 const {MeetingContextPanel}=require(path.join(frontend,'src/components/MeetingDetails/MeetingContextPanel.tsx'));
 const fixture=()=>({status:'needs_review',meeting_title:'Current title',notes:'Detailed evidence',recommendations:{title:{value:'Candidate title',state:'pending',reason:'Matching time'},customer:{value:'Acme',state:'pending',reason:'Calendar evidence'}}});
 recommendationFixture=fixture();let renderer;
 await act(async()=>{renderer=create(React.createElement(MeetingContextPanel,{meetingId:'m'}));});
 assert.ok(renderer.root.findAllByType('button').some(b=>b.children.includes('Accept both')));
 await act(async()=>{await renderer.root.findByProps({'aria-label':'Accept suggested title'}).props.onClick();});
 assert.equal(renderer.root.findAllByProps({'aria-label':'Accept suggested title'}).length,0);
 assert.equal(renderer.root.findAllByProps({'aria-label':'Dismiss suggested customer'}).length,1);
 await act(async()=>{await renderer.root.findByProps({'aria-label':'Dismiss suggested customer'}).props.onClick();});
 assert.equal(renderer.root.findAllByProps({'aria-label':'Calendar suggestions'}).length,0);
 act(()=>renderer.unmount());
 for(const label of ['Accept both','Dismiss both']){
  recommendationFixture=fixture();await act(async()=>{renderer=create(React.createElement(MeetingContextPanel,{meetingId:'m'}));});
  await act(async()=>{await renderer.root.findAllByType('button').find(b=>b.children.includes(label)).props.onClick();});
  const request=calls.findLast(c=>c.args?.request?.action==='review_recommendations').args.request;
  assert.deepEqual(Object.keys(request.decisions),['title','customer']);
  assert.equal(request.decisions.title.action,label==='Accept both'?'accept':'dismiss');
  act(()=>renderer.unmount());
 }
 recommendationFixture=null;
});
