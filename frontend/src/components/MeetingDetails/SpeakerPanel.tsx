'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {listen} from '@tauri-apps/api/event';
import {convertFileSrc, invoke} from '@tauri-apps/api/core';
import {SpeakerAssignment} from './SpeakerAssignment';
import {groupedSpeakers,SpeakerAnalysis} from '@/lib/speaker-labels';

export function SpeakerPanel({meetingId, disabled, onChange}: {
  meetingId:string; disabled:boolean; onChange:(value:SpeakerAnalysis|null)=>void;
}) {
  const [data,setData]=useState<SpeakerAnalysis|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [count,setCount]=useState('0');
  const countEdited=useRef(false);
  const [assignTarget,setAssignTarget]=useState<{id:string;name:string}|null>(null);
  const [saved,setSaved]=useState(false);
  const currentMeeting=useRef(meetingId);
  currentMeeting.current=meetingId;
  useEffect(()=>{
    let active=true;setData(null);setCount('0');countEdited.current=false;setError('');setBusy(false);onChange(null);
    invoke<SpeakerAnalysis>('speaker_action',{meetingId,action:'get'}).then(result=>{
      if(active){setData(result);if(!countEdited.current&&result.requested_speakers!=null&&result.requested_speakers>0){setCount(String(Math.max(0,result.requested_speakers)));countEdited.current=true;}onChange(result);}
    }).catch(reason=>{if(active)setError(String(reason));});
    return()=>{active=false;};
  },[meetingId,onChange]);
  const act=useCallback(async (action:string,extra:Record<string,unknown>={}) => {
    const requestedMeeting=meetingId;
    setBusy(true);setError('');setSaved(false);
    try{
      const result=await invoke<SpeakerAnalysis>('speaker_action',{meetingId,action,...extra});
      if(currentMeeting.current===requestedMeeting){setData(result);onChange(result);setSaved(action!=='analyze');}
    }catch(reason){if(currentMeeting.current===requestedMeeting)setError(String(reason));}
    finally{if(currentMeeting.current===requestedMeeting)setBusy(false);}
  },[meetingId,onChange]);
  useEffect(()=>{
    let active=true;
    let timer:NodeJS.Timeout|null=null;
    const refresh=()=>invoke<SpeakerAnalysis>('speaker_action',{meetingId,action:'get'}).then(result=>{
      if(active&&!busy){setData(result);onChange(result);}
    }).catch(()=>{});
    const listener=listen<string>('speaker-analysis-updated',event=>{if(event.payload===meetingId)void refresh();});
    const startPolling=()=>{
      if(timer)clearInterval(timer);
      if(data?.job_status==='queued'||data?.job_status==='running'){
        void refresh();
        timer=setInterval(()=>{if(data?.job_status==='queued'||data?.job_status==='running')void refresh();},5000);
      }
    };
    const stopPolling=()=>{if(timer){clearInterval(timer);timer=null;}};
    const onVisibilityChange=()=>{if(document.visibilityState==='visible'){startPolling();}else{stopPolling();}};
    if(document.visibilityState==='visible'){startPolling();}
    document.addEventListener('visibilitychange',onVisibilityChange);
    return()=>{active=false;stopPolling();document.removeEventListener('visibilitychange',onVisibilityChange);void listener.then(unlisten=>unlisten());};
  },[meetingId,onChange,busy,data?.job_status]);
  useEffect(()=>{
    const update=(event:Event)=>{const d=(event as CustomEvent).detail;if(d.meetingId===meetingId){setData(d.value);onChange(d.value);}};
    window.addEventListener('speaker-labels-saved',update);return()=>window.removeEventListener('speaker-labels-saved',update);
  },[meetingId,onChange]);
  useEffect(()=>{
    let active=true;
    const load=()=>invoke<{participants?:unknown[];calendar_title?:string;meet_title?:string}>('meeting_context_action',{request:{action:'get',meeting_id:meetingId}}).then(context=>{if(active&&!countEdited.current&&(context.calendar_title||context.meet_title))setCount(String(Math.min(20,context.participants?.length||0)));}).catch(()=>{});
    void load();const timer=setInterval(load,15000);return()=>{active=false;clearInterval(timer);};
  },[meetingId]);
  const groups=groupedSpeakers(data);
  const running=busy||data?.job_status==='queued'||data?.job_status==='running';
  const voice=(speaker:SpeakerAnalysis['speakers'][number],labels?:string[])=><div key={speaker.id} className="space-y-2 border-b py-3">
    <div className="font-semibold">{speaker.status==='unknown'?'Unidentified speaker':speaker.name}</div>
    <div className="text-xs text-gray-500">{labels?.join(' + ')||`Voice ${speaker.id}`}</div>
    {speaker.sample_path&&<audio controls preload="none" src={convertFileSrc(speaker.sample_path)} className="h-9 w-full"/>}
    <button type="button" disabled={running||disabled} className="meaty-action" onClick={()=>setAssignTarget({id:speaker.id,name:speaker.name})}>{speaker.status==='unknown'?'Identify':'Change person'}</button>
  </div>;
  return <section className="border-b p-4 text-sm space-y-3" aria-label="Speakers">
    <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">Speakers</h2><span className="font-mono text-xl font-bold" aria-label={`${groups.known.length} identified people, ${groups.unresolved.length} unresolved voices`}>{groups.known.length} / {groups.unresolved.length}</span></div>
    <fieldset disabled={running||disabled} className="flex flex-wrap items-end gap-3 disabled:opacity-60">
      <div><label htmlFor="expected-speakers" className="mb-2 block">Expected speakers</label><div className="meaty-speaker-stepper">
        <input id="expected-speakers" aria-label="Expected speakers; zero means unknown" type="number" min={0} max={20} step={1} value={count} onChange={e=>{countEdited.current=true;setCount(e.target.value);}}/>
        <div><button type="button" aria-label="Increase expected speakers" onClick={()=>{countEdited.current=true;setCount(String(Math.min(20,(Number(count)||0)+1)));}}>▴</button><button type="button" aria-label="Decrease expected speakers" onClick={()=>{countEdited.current=true;setCount(String(Math.max(0,(Number(count)||0)-1)));}}>▾</button></div>
      </div></div>
      <button type="button" className="meaty-action meaty-yellow-action" onClick={()=>{const n=Number(count);if(!Number.isInteger(n)||n<0||n>20){setError('Enter a whole number from 0 to 20.');return;}void act('analyze',{numSpeakers:n||-1,force:!!data?.segments.length});}}>{running?'Detecting…':'Detect speakers'}</button>
    </fieldset>
    {running&&<p role="status" aria-live="polite" className="flex items-center gap-2"><span className="meaty-busy-indicator"/>Detecting speakers…</p>}
    {data?.job_status==='failed'&&<p role="alert">{data.job_error||'Detection failed. Try again.'}</p>}
    {data?.learning_notice&&<p role="status">{data.learning_notice}</p>}
    {saved&&<p role="status">Speaker saved.</p>}
    {data?.analysis_warning&&<p role="alert">{data.analysis_warning}</p>}
    {!data?.analysis_warning&&groups.known.map(group=>voice(group[0],group.map(s=>`Voice ${s.id}`)))}
    <details><summary className="cursor-pointer font-semibold">Unresolved voices ({groups.unresolved.length})</summary>{!data?.analysis_warning&&groups.unresolved.map(s=>voice(s))}</details>
    {error&&<p role="alert" className="text-red-700">{error}</p>}
    {assignTarget&&<SpeakerAssignment key={`${meetingId}:${assignTarget.id}`} meetingId={meetingId} target={assignTarget} data={data} onClose={()=>setAssignTarget(null)} onSave={value=>{setData(value);onChange(value);setSaved(true);}}/>}
  </section>;
}
