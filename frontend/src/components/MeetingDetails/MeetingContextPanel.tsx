'use client';
import {useEffect,useRef,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {Pencil} from 'lucide-react';
import {useSidebar} from '@/components/Sidebar/SidebarProvider';

type Recommendation={value:string;reason:string;state:'pending'|'accepted'|'dismissed'};
type Context={meet_context_ready?:boolean;queue_delayed?:boolean;meet_title?:string;participants?:{name:string}[];recommendations?:Partial<Record<'title'|'customer',Recommendation>>;meeting_title?:string;calendar_title?:string;status:string;notes?:string;classification?:string;manual_companies?:string[];companies?:{name:string}[]};
export function MeetingContextPanel({meetingId,onTitleChange}:{meetingId:string;onTitleChange?:(title:string)=>void}){
 const [data,setData]=useState<Context|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [assignment,setAssignment]=useState('automatic'),[customers,setCustomers]=useState(''),[saving,setSaving]=useState(false),[editing,setEditing]=useState(false);
 const [reviewBusy,setReviewBusy]=useState(false),[suggestionEdit,setSuggestionEdit]=useState<'title'|'customer'|null>(null),[suggestionDraft,setSuggestionDraft]=useState('');
 const dirty=useRef(false);
 const {refetchMeetings}=useSidebar();
 useEffect(()=>{if(!data||dirty.current)return;const manual=data.manual_companies||[];setAssignment(manual.length?(manual.length===1&&manual[0].toLowerCase()==='internal'?'internal':'customer'):'automatic');setCustomers(manual.filter(n=>n.toLowerCase()!=='internal').join('\n'));},[data]);
 const previous=useRef('');
 const titleCallback=useRef(onTitleChange);titleCallback.current=onTitleChange;
 const lastTitle=useRef('');
 useEffect(()=>{
  let active=true;
  const load=()=>invoke<Context>('meeting_context_action',{request:{action:'get',meeting_id:meetingId}}).then(value=>{
   if(!active)return;setData(value);
   if(value.meeting_title&&lastTitle.current!==value.meeting_title){lastTitle.current=value.meeting_title;titleCallback.current?.(value.meeting_title);}
   if(value.status!=='pending'&&previous.current==='pending')void refetchMeetings();
   previous.current=value.status;
  }).catch(e=>{if(active)setError(String(e));});
  setData(null);previous.current='';void load();const timer=setInterval(load,5000);
  return()=>{active=false;clearInterval(timer);};
 },[meetingId,refetchMeetings]);
 async function queue(){setBusy(true);setError('');try{setData(await invoke<Context>('meeting_context_action',{request:{action:'queue',meeting_id:meetingId}}));previous.current='pending';}catch(e){setError(String(e));}finally{setBusy(false);}}
 async function saveAssignment(){
  const names=customers.split('\n').map(n=>n.trim()).filter(Boolean);
  if(assignment==='customer'&&!names.length){setError('Enter a customer name.');return;}
  setSaving(true);setError('');
  try{const value=await invoke<Context>('meeting_context_action',{request:{action:'classify',meeting_id:meetingId,manual_companies:assignment==='internal'?['Internal']:assignment==='customer'?names:[]}});dirty.current=false;setData(value);setEditing(false);await refetchMeetings();}
  catch(e){setError(String(e));}finally{setSaving(false);}
 }
 const suggestions=(['title','customer'] as const).filter(field=>{
  const item=data?.recommendations?.[field];if(!item||item.state!=='pending')return false;
  const current=field==='title'?data?.meeting_title:data?.classification==='internal'?'Internal':data?.companies?.map(c=>c.name).join(', ');
  return item.value!==current;
 });
 async function reviewSuggestions(fields:('title'|'customer')[],action:'accept'|'dismiss',editValue?:string){
  setReviewBusy(true);setError('');
  try{const decisions=Object.fromEntries(fields.map(field=>[field,{action,expected:data?.recommendations?.[field]?.value,...(editValue!==undefined?{value:editValue}:{})}]));
   const value=await invoke<Context>('meeting_context_action',{request:{action:'review_recommendations',meeting_id:meetingId,decisions}});
   setData(value);setSuggestionEdit(null);if(value.meeting_title){lastTitle.current=value.meeting_title;titleCallback.current?.(value.meeting_title);}await refetchMeetings();
  }catch(e){setError(String(e));}finally{setReviewBusy(false);}
 }
 const pending=busy||(data?.status==='pending'&&!data?.queue_delayed&&!data?.meet_context_ready);
 return <section className="border-b p-4 text-sm space-y-3">
  <div className="space-y-3 border-b pb-4">
   <div className="flex items-center justify-between gap-3">
    <div className="min-w-0"><h2 className="meaty-panel-label">Customer / internal</h2><p className="mt-1 break-words font-semibold" aria-live="polite">{data?.classification==='internal'?'Internal':data?.companies?.map(c=>c.name).join(', ')||'Unassigned'}</p></div>
    <button type="button" aria-label="Edit meeting assignment" aria-expanded={editing} aria-controls="customer-assignment-editor" disabled={!data||saving} className="meaty-assignment-edit shrink-0" onClick={()=>setEditing(true)}><Pencil className="h-4 w-4" aria-hidden="true"/></button>
   </div>
   {editing&&<fieldset id="customer-assignment-editor" disabled={!data||saving} className="meaty-assignment-editor space-y-3 disabled:opacity-60">
    <label className="block font-semibold">Assign meeting to<select aria-label="Assign meeting to" value={assignment} onChange={e=>{dirty.current=true;setAssignment(e.target.value);}} className="mt-1 w-full border p-2"><option value="automatic">Automatic</option><option value="internal">Internal</option><option value="customer">Customer</option></select></label>
    {assignment==='customer'&&<label className="block font-semibold">Customer name<textarea aria-label="Customer name" rows={2} value={customers} onChange={e=>{dirty.current=true;setCustomers(e.target.value);}} className="mt-1 w-full border p-2" placeholder="Customer name"/></label>}
    <div className="flex flex-wrap gap-3"><button type="button" disabled={!dirty.current} onClick={saveAssignment} className="meaty-action meaty-yellow-action">{saving?'Saving…':'Save assignment'}</button><button type="button" className="meaty-action" onClick={()=>{dirty.current=false;const manual=data?.manual_companies||[];setAssignment(manual.length?(manual.length===1&&manual[0].toLowerCase()==='internal'?'internal':'customer'):'automatic');setCustomers(manual.filter(n=>n.toLowerCase()!=='internal').join('\n'));setEditing(false);setError('');}}>Cancel</button></div>
   </fieldset>}
  </div>
  {!!suggestions.length&&<section className="meaty-calendar-suggestions space-y-3" aria-label="Calendar suggestions" aria-busy={reviewBusy}>
   <h2 className="meaty-panel-label">Suggested from calendar</h2>
   {suggestions.map(field=>{const item=data!.recommendations![field]!;return <div key={field} className="meaty-suggestion-row space-y-2">
    <div className="text-xs">{field==='title'?'Meeting title':'Customer'}</div><p className="font-semibold break-words">{item.value}</p><p className="text-xs text-gray-600">{item.reason}</p>
    {suggestionEdit===field?<div className="space-y-2"><label className="block">{field==='title'?'Edit suggested title':'Edit suggested customer'}<input aria-label={field==='title'?'Edit suggested title':'Edit suggested customer'} maxLength={field==='title'?500:200} className="mt-1 w-full border p-2" value={suggestionDraft} disabled={reviewBusy} onChange={e=>setSuggestionDraft(e.target.value)}/></label><div className="flex flex-wrap gap-2"><button type="button" className="meaty-suggestion-small" disabled={reviewBusy||!suggestionDraft.trim()} onClick={()=>void reviewSuggestions([field],'accept',suggestionDraft)}>Save & accept</button><button type="button" className="meaty-suggestion-small" disabled={reviewBusy} onClick={()=>setSuggestionEdit(null)}>Cancel</button></div></div>:<div className="flex flex-wrap gap-2"><button type="button" className="meaty-suggestion-small meaty-suggestion-accept" aria-label={`Accept suggested ${field}`} disabled={reviewBusy} onClick={()=>void reviewSuggestions([field],'accept')}>Accept</button><button type="button" className="meaty-suggestion-small" aria-label={`Edit suggested ${field}`} disabled={reviewBusy} onClick={()=>{setSuggestionEdit(field);setSuggestionDraft(item.value);}}>Edit</button><button type="button" className="meaty-suggestion-small" aria-label={`Dismiss suggested ${field}`} disabled={reviewBusy} onClick={()=>void reviewSuggestions([field],'dismiss')}>Dismiss</button></div>}
   </div>;})}
   {suggestions.length===2&&<div className="flex flex-wrap gap-3"><button type="button" className="meaty-action meaty-yellow-action" disabled={reviewBusy||suggestionEdit!==null} onClick={()=>void reviewSuggestions(['title','customer'],'accept')}>Accept both</button><button type="button" className="meaty-action" disabled={reviewBusy||suggestionEdit!==null} onClick={()=>void reviewSuggestions(['title','customer'],'dismiss')}>Dismiss both</button></div>}
   {reviewBusy&&<p role="status">Saving your choices…</p>}
  </section>}
  {data?.meet_title&&<p className="text-xs text-gray-500">From Google Meet · {data.meet_title}</p>}
  {!!data?.participants?.length&&<p className="text-xs text-gray-500">Meeting people: {data.participants.map(p=>p.name).filter(Boolean).join(', ')}</p>}
  {data?.calendar_title&&<p className="text-xs text-gray-500">From calendar · {data.calendar_title}</p>}
  <button type="button" disabled={pending} onClick={queue} className="meaty-action meaty-yellow-action">{busy?'Queuing calendar lookup…':pending?'Calendar lookup queued':'Check calendar'}</button>
  {pending&&<p role="status" aria-live="polite" className="flex items-center gap-2"><span className="meaty-busy-indicator"/>Queued for the background calendar check. Checks run about every five minutes while this Mac, Codex and signed-in Chrome are available.</p>}
  {data?.meet_context_ready&&data.status==='pending'&&<p className="text-xs text-gray-500">Meeting details received from Google Meet. Calendar enrichment continues in the background.</p>}
  {data?.queue_delayed&&<p role="status" className="text-xs text-gray-600">Still waiting for the background calendar worker. You can keep using Meaty; any result will appear here. Google Meet names and title are available immediately when sent by the extension.</p>}
  {data?.status==='needs_review'&&data.notes&&<details className="text-xs"><summary className="cursor-pointer">Calendar match details</summary><p className="mt-2">{data.notes}</p></details>}
  {error&&<p role="alert" className="text-red-700">{error}</p>}
 </section>;
}
