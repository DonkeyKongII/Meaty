'use client';
import {useEffect,useState} from 'react';
import {invoke,convertFileSrc} from '@tauri-apps/api/core';
import {SpeakerAnalysis,SpeakerTag} from '@/lib/speaker-labels';
export type Profile={id:string;name:string};
export function ProfileSearch({meetingId,onSelect,suggestions=[]}:{meetingId:string;onSelect:(profile:Profile)=>void;suggestions?:Profile[]}) {
 const [query,setQuery]=useState(''),[offset,setOffset]=useState(0),[items,setItems]=useState<Profile[]>([]),[more,setMore]=useState(false),[error,setError]=useState(''),[loading,setLoading]=useState(false),[participants,setParticipants]=useState<string[]>([]);
 useEffect(()=>{let active=true;invoke<{participants?:{name:string}[]}>('meeting_context_action',{request:{action:'get',meeting_id:meetingId}}).then(v=>{if(active)setParticipants([...new Set((v.participants||[]).map(p=>p.name).filter(Boolean))]);}).catch(()=>{});return()=>{active=false;};},[meetingId]);
 useEffect(()=>{let active=true;setLoading(true);setError('');if(!query.trim()){setItems([]);setMore(false);setLoading(false);return()=>{active=false;};}const timer=setTimeout(()=>{
  invoke<{items:Profile[];has_more:boolean}>('speaker_action',{meetingId,action:'search',query,offset}).then(r=>{if(active){setItems(r.items);setMore(r.has_more);}}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setLoading(false);});
 },250);return()=>{active=false;clearTimeout(timer);};},[meetingId,query,offset]);
 async function selectParticipant(name:string){
  setLoading(true);setError('');
  try{const result=await invoke<{items:Profile[]}>('speaker_action',{meetingId,action:'search',query:name,offset:0});
   const exact=result.items.filter(p=>p.name.trim().toLowerCase()===name.trim().toLowerCase());
   if(exact.length>1){setQuery(name);setOffset(0);}else onSelect(exact[0]||{id:'',name});
  }catch(e){setError(String(e));}finally{setLoading(false);}
 }
 return <div className="space-y-2">
  <label className="block">Find a saved speaker<input autoFocus aria-label="Find a saved speaker" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0);}} className="mt-1 w-full rounded border p-2" placeholder="Search by name"/></label>
  {!query&&!!participants.length&&<div><p className="text-xs text-gray-500">Meeting people & calendar invitees</p>{participants.map(name=><button type="button" key={name} className="mr-2 text-blue-700" disabled={loading} onClick={()=>void selectParticipant(name)}>{name}</button>)}</div>}
  {!query&&!!suggestions.length&&<div><p className="text-xs text-gray-500">From this meeting</p>{suggestions.slice(0,10).map(p=><button type="button" key={p.id} className="mr-2 text-blue-700" onClick={()=>onSelect(p)}>{p.name}</button>)}</div>}
  <div className="max-h-48 overflow-y-auto" aria-label="Saved speaker results">{loading?<p role="status">Searching…</p>:items.map(p=><button type="button" key={p.id} onClick={()=>onSelect(p)} className="block w-full rounded p-2 text-left hover:bg-gray-100">{p.name}</button>)}</div>
  {!loading&&!!query.trim()&&!items.length&&<p className="text-xs text-gray-500">No saved speakers found.</p>}
  {!!query.trim()&&<div className="flex gap-3"><button type="button" disabled={loading||!offset} onClick={()=>setOffset(v=>Math.max(0,v-20))}>Previous</button><button type="button" disabled={loading||!more} onClick={()=>setOffset(v=>v+20)}>Next</button></div>}
  {error&&<p role="alert" className="text-red-700">{error}</p>}
 </div>;
}
export function SpeakerAssignment({meetingId,target,data,onSave,onClose,live=false}:{live?:boolean;meetingId:string;target:SpeakerTag;data:SpeakerAnalysis|null;onSave:(data:SpeakerAnalysis)=>void;onClose:()=>void}) {
 const [chosen,setChosen]=useState<Profile|null>(null),[name,setName]=useState(''),[remember,setRemember]=useState(!live),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const speaker=data?.speakers.find(s=>s.id===target.id);
 async function save(){setBusy(true);setError('');try{
  const result=await invoke<SpeakerAnalysis>('speaker_action',{meetingId,action:'assign',speakerId:target.id,profileId:chosen?.id||null,name:chosen?.name||name.trim(),remember});onSave(result);onClose();
 }catch(e){setError(String(e));}finally{setBusy(false);}}
 async function removeTag(){
  if(!target.canRemove||target.start==null||target.end==null)return;
  setBusy(true);setError('');try{
   const speakerId=JSON.stringify({id:target.sourceId||target.id,start:target.start,end:target.end});
   const result=await invoke<SpeakerAnalysis>('speaker_action',{meetingId,action:'remove_tag',speakerId});onSave(result);onClose();
  }catch(e){setError(String(e));}finally{setBusy(false);}
 }
 return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onKeyDown={e=>{if(e.key==='Escape'&&!busy)onClose();}}><div role="dialog" aria-modal="true" aria-label="Assign speaker" className="max-h-[90vh] w-full max-w-md space-y-4 overflow-y-auto rounded-lg bg-white p-5 shadow-xl">
  <div className="flex justify-between"><h2 className="font-semibold">Assign speaker</h2><button type="button" aria-label="Close speaker assignment" disabled={busy} onClick={onClose}>Close</button></div>
  <p className="text-sm text-gray-600">{target.id.startsWith('__span__:')?'This speech has no detected voice group. This assignment applies to the selected transcript segment.':'Applies to every segment belonging to this detected voice in this meeting.'}</p>
  {speaker?.sample_path&&<audio controls src={convertFileSrc(speaker.sample_path)} className="w-full"/>}
  <fieldset disabled={busy} className="space-y-3">
   <ProfileSearch meetingId={meetingId} suggestions={data?.profiles} onSelect={p=>{setChosen(p);setName('');}}/>
   <label className="block text-sm">Or create a new speaker<input aria-label="New speaker name" maxLength={100} value={name} onChange={e=>{setName(e.target.value);setChosen(null);}} className="mt-1 w-full rounded border p-2" placeholder="Full name"/></label>
   {(chosen||name.trim())&&<p>Assign to <strong>{chosen?.name||name.trim()}</strong>{!chosen?' (new speaker)':''}</p>}
   {!live&&<><label className="block text-sm"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)} className="mr-2"/>Remember and improve this voice for future meetings</label>
   <p className="text-xs text-gray-500">Confirmed assignments add clean voice samples. Short or mixed speech is labeled here without changing voice matching.</p></>}
   {live&&<p className="text-xs text-gray-500">Labels this timestamp’s transcript passage. The label stays with the saved meeting.</p>}
   <button type="button" disabled={!chosen&&!name.trim()} onClick={save} className="rounded bg-blue-600 px-3 py-2 text-white disabled:opacity-50">{busy?'Saving voice & checking matches…':'Save speaker'}</button>
  </fieldset>
  {target.canRemove&&<button type="button" disabled={busy} onClick={removeTag} className="meaty-action text-red-700">Remove speaker from this passage</button>}
  {error&&<p role="alert" className="text-red-700">{error}</p>}
 </div></div>;
}
