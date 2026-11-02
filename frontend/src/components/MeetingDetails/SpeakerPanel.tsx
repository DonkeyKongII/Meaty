'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {convertFileSrc, invoke} from '@tauri-apps/api/core';
import {SpeakerAnalysis} from '@/lib/speaker-labels';

export function SpeakerPanel({meetingId, disabled, onChange}: {
  meetingId:string; disabled:boolean; onChange:(value:SpeakerAnalysis|null)=>void;
}) {
  const [data,setData]=useState<SpeakerAnalysis|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [count,setCount]=useState('');
  const [autoAnalyze,setAutoAnalyze]=useState(true);
  const autoAttempted=useRef(new Set<string>());
  useEffect(()=>{setAutoAnalyze(localStorage.getItem('meetily.autoSpeakerAnalysis')!=='false');},[]);
  const currentMeeting=useRef(meetingId);
  currentMeeting.current=meetingId;
  useEffect(()=>{
    let active=true;setData(null);setError('');setBusy(false);onChange(null);
    invoke<SpeakerAnalysis>('speaker_action',{meetingId,action:'get'}).then(result=>{
      if(active){setData(result);onChange(result);}
    }).catch(reason=>{if(active)setError(String(reason));});
    return()=>{active=false;};
  },[meetingId,onChange]);
  const act=useCallback(async (action:string,extra:Record<string,unknown>={}) => {
    const requestedMeeting=meetingId;
    setBusy(true);setError('');
    try{
      const result=await invoke<SpeakerAnalysis>('speaker_action',{meetingId,action,...extra});
      if(currentMeeting.current===requestedMeeting){setData(result);onChange(result);}
    }catch(reason){if(currentMeeting.current===requestedMeeting)setError(String(reason));}
    finally{if(currentMeeting.current===requestedMeeting)setBusy(false);}
  },[meetingId,onChange]);
  useEffect(()=>{
    if(autoAnalyze&&!disabled&&!busy&&data?.profiles.length&&!data.segments.length&&!autoAttempted.current.has(meetingId)){
      autoAttempted.current.add(meetingId);void act('analyze');
    }
  },[autoAnalyze,disabled,busy,data,meetingId,act]);
  return <details className="border-b border-gray-200 p-3 text-sm">
    <summary className="cursor-pointer font-medium">Speakers {data?.speakers.length ? `(${data.speakers.length})` : ''}</summary>
    <div className="mt-3 max-h-[38vh] space-y-3 overflow-y-auto pr-2">
      <p className="text-gray-600">Identify voices after recording. Listen to a sample, name the speaker, and optionally save their voice for future meetings. Audio and voice profiles stay on this Mac.</p>
      <label className="block"><input type="checkbox" checked={autoAnalyze} onChange={e=>{setAutoAnalyze(e.target.checked);localStorage.setItem('meetily.autoSpeakerAnalysis',String(e.target.checked));}} className="mr-2"/>Automatically identify voices when opening saved meetings, once a voice profile exists</label>
      <fieldset disabled={busy||disabled} className="space-y-3 disabled:opacity-60">
        <div className="flex items-center gap-2">
          <label>Speaker count <input aria-label="Speaker count (leave empty for automatic)" type="number" min={1} max={20} placeholder="Auto" value={count} onChange={e=>setCount(e.target.value)} className="w-20 rounded border p-1"/></label>
          <button type="button" className="rounded border px-3 py-1" onClick={()=>act('analyze',{numSpeakers:count?Number(count):-1,force:!!data?.segments.length})}>{data?.segments.length?'Re-detect speakers':'Detect speakers'}</button>
        </div>
        {!!data?.segments.length && <p className="text-xs text-gray-500">Re-detecting replaces this meeting’s speaker labels. Saved voice profiles remain.</p>}
        {data?.speakers.map(speaker=><form key={`${meetingId}:${speaker.id}:${speaker.name}`} className="space-y-2 rounded border p-3" onSubmit={event=>{
          event.preventDefault();
          const form=new FormData(event.currentTarget);
          const profileId=String(form.get('profile')||'');
          const existing=data.profiles.find(profile=>profile.id===profileId);
          const name=existing?.name||String(form.get('name')||'');
          act(form.get('remember')?'enroll':'label',{speakerId:speaker.id,profileId:profileId||null,name});
        }}>
          <div className="font-medium">{speaker.name} <span className="font-normal text-gray-500">{speaker.status==='recognized'?'— voice match':speaker.status==='unknown'?'— unnamed voice':''}</span></div>
          {speaker.mixed && <p className="text-amber-700">This group may contain mixed voices. Re-detect with a speaker count before saving a voice profile.</p>}
          {speaker.sample_path && <audio aria-label={`Voice sample for ${speaker.name}`} controls preload="none" src={convertFileSrc(speaker.sample_path)} className="h-9 w-full"/>}
          <div className="flex flex-wrap gap-2">
            <input name="name" aria-label={`Name for ${speaker.name}`} defaultValue={speaker.status==='unknown'?'':speaker.name} maxLength={100} placeholder="Speaker name" className="min-w-0 rounded border px-2 py-1"/>
            <select name="profile" aria-label={`Saved profile for ${speaker.name}`} defaultValue="" className="min-w-0 rounded border px-2 py-1"><option value="">New person / name above</option>{data.profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>
          </div>
          <label className="block"><input name="remember" type="checkbox" disabled={!speaker.can_enroll} className="mr-2"/>Remember this voice in future meetings</label>
          {!speaker.can_enroll && <p className="text-xs text-gray-500">You can name this speaker here. Saving a reusable voice needs a current analysis with at least 8 seconds of clear speech.</p>}
          <button type="submit" className="rounded border px-3 py-1">Save speaker</button>
        </form>)}
        {!!data?.profiles.length && <details><summary className="cursor-pointer">Saved voice profiles ({data.profiles.length})</summary>
          <p className="my-2 text-xs text-gray-500">Deleting a profile removes its saved voice match. Historical meeting labels and audio remain.</p>
          {data.profiles.map(profile=><form key={`${profile.id}:${profile.name}`} className="my-2 flex flex-wrap gap-2" onSubmit={e=>{e.preventDefault();act('rename',{profileId:profile.id,name:String(new FormData(e.currentTarget).get('name')||'')});}}>
            <input name="name" aria-label={`Rename profile ${profile.name}`} defaultValue={profile.name} maxLength={100} className="min-w-0 rounded border p-1"/>
            <button type="submit" className="rounded border px-2">Rename</button>
            <button type="button" onClick={()=>act('forget',{profileId:profile.id})} className="rounded border px-2">Delete voice profile</button>
          </form>)}
        </details>}
      </fieldset>
      <div role="status" aria-live="polite">{busy?'Analyzing or saving speakers locally… This can take several minutes.':''}</div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {data && !busy && !error && !data.segments.length && <p className="text-xs text-gray-500">No speaker analysis yet. Very short clips or silence may not contain enough speech.</p>}
    </div>
  </details>;
}
