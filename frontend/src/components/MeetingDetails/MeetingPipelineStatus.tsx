'use client';
import {useEffect,useState,useRef} from 'react';
import {invoke} from '@tauri-apps/api/core';
export type Pipeline={speaker:string;calendar:string;status:string;cleanup?:string;cleanup_error?:string;error?:string;timed_out:boolean};
export function MeetingPipelineStatus({meetingId,onComplete}:{meetingId:string;onComplete?:()=>Promise<void>}){
 const onCompleteRef=useRef(onComplete);onCompleteRef.current=onComplete;
 const refreshed=useRef('');
 const [retrying,setRetrying]=useState(false);
 const [retryError,setRetryError]=useState('');
 const retry=async()=>{setRetrying(true);setRetryError('');try{await invoke('retry_transcript_cleanup',{meetingId});setData(v=>v?{...v,cleanup:'queued',cleanup_error:undefined,error:undefined,status:'waiting'}:v);}catch(e){setRetryError(String(e));}finally{setRetrying(false);}};
 const [data,setData]=useState<Pipeline|null>(null);
 useEffect(()=>{
  let active=true;
  let timer:NodeJS.Timeout|null=null;
  const load=()=>{
   invoke<Pipeline>('meeting_pipeline_status',{meetingId}).then(v=>{
    if(!active)return;
    setData(v);
    if(v.cleanup==='complete'&&refreshed.current!==meetingId){refreshed.current=meetingId;void onCompleteRef.current?.();}
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
 const cleaning=data.cleanup==='queued'||data.cleanup==='running';
 return <div role="status" className="border-b bg-blue-50 p-3 text-xs text-gray-700">
  <p>{cleaning?'Cleaning up the recorded conversation…':data.cleanup==='failed'?'Transcript cleanup needs attention':waiting?'Preparing meeting automatically…':data.status==='failed'?'Automatic summary needs attention':data.status==='cancelled'?'Automatic summary cancelled.':data.status==='ready'?'Meeting context ready. Automatic summary is off.':'Meeting pipeline: summary requested.'}</p>
  <p>Transcript cleanup: {(data.cleanup||'not queued').replaceAll('_',' ')} · Speakers: {data.speaker.replaceAll('_',' ')} · Calendar lookup: {data.calendar.replaceAll('_',' ')}</p>
  {cleaning&&<p>The live transcript is provisional. Summaries wait until cleanup succeeds. You can leave this page.</p>}
  {waiting&&!cleaning&&<p>Transcript cleanup is complete. The summary waits for speaker and calendar context, up to six minutes.</p>}
  {data.cleanup==='failed'&&<><p role="alert">{data.cleanup_error} The summary is on hold; the recording is kept.</p><button type="button" className="meaty-action" disabled={retrying} onClick={()=>void retry()}>{retrying?'Retrying…':'Retry transcript cleanup'}</button></>}
  {retryError&&<p role="alert">{retryError}</p>}
  {data.timed_out&&(data.calendar==='pending'||data.speaker==='running'||data.speaker==='queued')&&<p>Preparation reached its time limit. The summary uses the context available; remaining work continues in the background.</p>}
  {data.error&&<p role="alert" className="text-red-700">{data.error}</p>}
 </div>;
}
