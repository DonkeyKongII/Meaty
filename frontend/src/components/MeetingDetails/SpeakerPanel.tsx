'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {listen} from '@tauri-apps/api/event';
import {convertFileSrc, invoke} from '@tauri-apps/api/core';
import {ProfileSearch,SpeakerAssignment,Profile} from './SpeakerAssignment';
import {SpeakerAnalysis} from '@/lib/speaker-labels';

export function SpeakerPanel({meetingId, disabled, onChange}: {
  meetingId:string; disabled:boolean; onChange:(value:SpeakerAnalysis|null)=>void;
}) {
  const [data,setData]=useState<SpeakerAnalysis|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [count,setCount]=useState('');
  const [assignTarget,setAssignTarget]=useState<{id:string;name:string}|null>(null);
  const [profilesOpen,setProfilesOpen]=useState(false);
  const [managed,setManaged]=useState<Profile|null>(null);
  const [saved,setSaved]=useState(false);
  const currentMeeting=useRef(meetingId);
  currentMeeting.current=meetingId;
  useEffect(()=>{
    let active=true;setData(null);setCount('');setError('');setBusy(false);onChange(null);
    invoke<SpeakerAnalysis>('speaker_action',{meetingId,action:'get'}).then(result=>{
      if(active){setData(result);if(result.requested_speakers&&result.requested_speakers>0)setCount(String(result.requested_speakers));onChange(result);}
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
  return <details className="border-b border-gray-200 p-3 text-sm">
    <summary className="cursor-pointer font-medium">Speakers {data?.analysis_warning?'— re-analysis needed':data?.speakers.length?`(${data.speakers.length})`:''}</summary>
    <div className="mt-3 max-h-[38vh] space-y-3 overflow-y-auto pr-2">
      <p className="text-gray-600">Detected speakers are saved automatically. Listen to a sample, name the speaker, and optionally save their voice for future meetings. Audio and voice profiles stay on this Mac. After saving speaker names, regenerate the summary to use those assignments.</p>
      <p className="text-xs text-gray-600">Speaker detection runs automatically after a meeting is saved. You can retry or adjust the count below.</p>
      {data?.participant_count&&<p className="text-xs text-gray-600">Peak observed attendance: {data.participant_count}. Attendees who never spoke may not form a voice group.</p>}
      {(data?.job_status==='queued'||data?.job_status==='running')&&<p role="status">{data.job_status==='queued'?'Speaker detection queued.':'Detecting speakers in the background… You can leave this meeting.'}</p>}
      {data?.job_status==='failed'&&<p role="alert" className="text-amber-800">Automatic detection could not finish: {data.job_error} Retry below.</p>}
      {data?.learning_notice&&<p role="status" className="text-xs text-gray-600">{data.learning_notice}</p>}
      {saved&&<p role="status" className="text-green-700">Speaker saved.</p>}
      {!!data?.unassigned_seconds && <p className="text-xs text-gray-600">About {Math.round(data.unassigned_seconds)} seconds of speech could not be assigned reliably. These passages remain unassigned rather than creating extra speakers.</p>}
      {data?.analysis_warning && <p role="alert" className="text-amber-800">{data.analysis_warning}</p>}
      <p className="text-xs text-gray-600">For meetings, enter the known number of people who spoke. Automatic counts are experimental and can split one person into many groups.</p>
      <fieldset disabled={busy||disabled||data?.job_status==='running'} className="space-y-3 disabled:opacity-60">
        <div className="flex items-center gap-2">
          <label>Speaker count <input aria-label="Speaker count (leave empty for automatic)" type="number" min={1} max={20} placeholder="Known count" value={count} onChange={e=>setCount(e.target.value)} className="w-20 rounded border p-1"/></label>
          <button type="button" className="rounded border px-3 py-1" onClick={()=>act('analyze',{numSpeakers:count?Number(count):-1,force:!!data?.segments.length})}>{data?.segments.length?'Re-detect speakers':'Detect speakers'}</button>
        </div>
        {!!data?.segments.length && <p className="text-xs text-gray-500">Re-detecting replaces this meeting’s speaker labels. Saved voice profiles remain.</p>}
        {!data?.analysis_warning&&data?.speakers.map(speaker=><div key={speaker.id} className="space-y-2 rounded border p-3">
          <div className="font-medium">{speaker.status==='unknown'?'Unidentified speaker':speaker.name}</div>
          {speaker.sample_path&&<audio controls preload="none" src={convertFileSrc(speaker.sample_path)} className="h-9 w-full"/>}
          <button type="button" className="text-blue-700" onClick={()=>setAssignTarget({id:speaker.id,name:speaker.name})}>Assign or change speaker</button>
        </div>)}
        <details onToggle={e=>setProfilesOpen(e.currentTarget.open)}><summary className="cursor-pointer">Saved speakers ({data?.profile_count??data?.profiles.length??0})</summary>
          {profilesOpen&&<ProfileSearch meetingId={meetingId} onSelect={setManaged}/>}
          {managed&&<form className="my-2 space-y-2" key={managed.id+managed.name} onSubmit={e=>{e.preventDefault();void act('rename',{profileId:managed.id,name:String(new FormData(e.currentTarget).get('name')||'')});setManaged(null);}}>
           <input name="name" aria-label="Rename saved speaker" defaultValue={managed.name} maxLength={100} className="rounded border p-1"/>
           <button type="submit" className="ml-2">Rename</button><button type="button" className="ml-2" onClick={()=>{void act('forget',{profileId:managed.id});setManaged(null);}}>Delete voice profile</button>
          </form>}
        </details>
      </fieldset>
      <div role="status" aria-live="polite">{busy?'Analyzing or saving speakers locally… This can take several minutes.':''}</div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {data && !busy && !error && !data.segments.length && <p className="text-xs text-gray-500">No speaker analysis yet. Very short clips or silence may not contain enough speech.</p>}
      {assignTarget&&<SpeakerAssignment key={`${meetingId}:${assignTarget.id}`} meetingId={meetingId} target={assignTarget} data={data} onClose={()=>setAssignTarget(null)} onSave={value=>{setData(value);onChange(value);setSaved(true);}}/>}
    </div>
  </details>;
}
