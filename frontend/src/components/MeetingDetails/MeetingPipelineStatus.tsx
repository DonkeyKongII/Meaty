'use client';
import {useEffect,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
type Pipeline={speaker:string;calendar:string;status:string;error?:string;timed_out:boolean};
export function MeetingPipelineStatus({meetingId}:{meetingId:string}){
 const [data,setData]=useState<Pipeline|null>(null);
 useEffect(()=>{let active=true;const load=()=>invoke<Pipeline>('meeting_pipeline_status',{meetingId}).then(v=>{if(active)setData(v);}).catch(()=>{});void load();const timer=setInterval(load,5000);return()=>{active=false;clearInterval(timer);};},[meetingId]);
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
