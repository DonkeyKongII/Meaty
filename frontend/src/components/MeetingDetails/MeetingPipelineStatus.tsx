'use client';
import {useEffect,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
export type Pipeline={speaker:string;calendar:string;status:string;error?:string;timed_out:boolean};
export function MeetingPipelineStatus({meetingId}:{meetingId:string}){
 const [data,setData]=useState<Pipeline|null>(null);
 useEffect(()=>{
  let active=true;
  let timer:NodeJS.Timeout|null=null;
  const load=()=>{
   invoke<Pipeline>('meeting_pipeline_status',{meetingId}).then(v=>{
    if(!active)return;
    setData(v);
    window.dispatchEvent(new CustomEvent('meeting-pipeline-updated',{detail:{meetingId,pipeline:v}}));
   }).catch(()=>{});
  };
  const start=()=>{
   if(timer)clearInterval(timer);
   load();
   timer=setInterval(load,5000);
  };
  const stop=()=>{
   if(timer){clearInterval(timer);timer=null;}
  };
  const onVisibilityChange=()=>{
   if(document.visibilityState==='visible'){start();}else{stop();}
  };
  if(document.visibilityState==='visible'){start();}
  document.addEventListener('visibilitychange',onVisibilityChange);
  return()=>{active=false;stop();document.removeEventListener('visibilitychange',onVisibilityChange);};
 },[meetingId]);
 if(!data||data.status==='not_queued')return null;
 const waiting=data.status==='waiting';
 return <div role="status" className="border-b bg-blue-50 p-3 text-xs text-gray-700">
  <p>{waiting?'Preparing meeting automatically…':data.status==='failed'?'Automatic summary needs attention':data.status==='cancelled'?'Automatic summary cancelled.':data.status==='ready'?'Meeting context ready. Automatic summary is off.':'Meeting pipeline: summary requested.'}</p>
  <p>Speakers: {data.speaker.replaceAll('_',' ')} · Calendar lookup: {data.calendar.replaceAll('_',' ')}</p>
  {waiting&&<p>The summary waits for both steps, up to six minutes. You can leave this page.</p>}
  {data.timed_out&&(data.calendar==='pending'||data.speaker==='running'||data.speaker==='queued')&&<p>Preparation reached its time limit. The summary uses the context available; remaining work continues in the background.</p>}
  {data.error&&<p role="alert" className="text-red-700">{data.error}</p>}
 </div>;
}
