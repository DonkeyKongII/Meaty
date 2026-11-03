'use client';
import {useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {useRouter} from 'next/navigation';
import {useSidebar} from '@/components/Sidebar/SidebarProvider';
import {useRecordingState} from '@/contexts/RecordingStateContext';
type Candidate={id:string;title:string;created_at:string;started_at:string};
export function CombineMeetingsPanel({meetingId}:{meetingId:string}) {
  const [open,setOpen]=useState(false),[meetings,setMeetings]=useState<Candidate[]>([]);
  const [selected,setSelected]=useState<string[]>([]),[title,setTitle]=useState('');
  const [audio,setAudio]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const {refetchMeetings,setCurrentMeeting}=useSidebar();const router=useRouter();
  const state=useRecordingState();
  const disabled=state.isRecording||state.isStartingRecording||state.isStopping||state.isSaving;
  async function show() {
    setError('');
    try {
      const rows=await invoke<Candidate[]>('meeting_context_action',{request:{action:'candidates'}});
      setMeetings(rows);setSelected([meetingId]);
      const previousTitle=rows.find(m=>m.id===meetingId)?.title||'';
      setTitle(/^Meeting[ _]\d/i.test(previousTitle)?'':previousTitle+' — combined');setOpen(true);
    }catch(e){setError(String(e));}
  }
  const ordered = meetings.filter(m=>selected.includes(m.id));
  async function combine() {
    setBusy(true);setError('');
    try {
      const meeting=await invoke<{id:string;title:string}>('meeting_context_action',{request:{action:'combine',meeting_ids:ordered.map(m=>m.id),title,include_audio:audio}});
      await refetchMeetings();setCurrentMeeting(meeting);setOpen(false);router.push(`/meeting-details?id=${encodeURIComponent(meeting.id)}`);
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <div className="border-b p-3 text-sm">
    <button disabled={disabled||busy} className="meaty-action text-blue-600 disabled:text-gray-400" onClick={show}>Combine meetings…</button>
    {disabled&&<span className="ml-2 text-xs text-gray-500">Available after recording finishes</span>}
    {open&&<div role="dialog" aria-modal="true" aria-label="Combine meetings" className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6">
      <div className="w-full max-w-xl max-h-[85vh] overflow-y-auto rounded-xl bg-white p-5 shadow-xl space-y-4">
        <h2 className="text-lg font-semibold">Combine meetings</h2>
        <p>Create a new meeting from 2–10 recordings in date/time order, earliest first. Original recordings, notes, speaker assignments and portal tasks stay available.</p>
        <label className="block">New meeting title<input autoFocus maxLength={200} className="border rounded p-2 w-full" value={title} onChange={e=>setTitle(e.target.value)} disabled={busy}/></label>
        <fieldset disabled={busy} className="space-y-2"><legend className="font-medium">Choose recordings</legend>
          <div className="max-h-40 overflow-y-auto rounded border p-2 space-y-2">{meetings.map(m=><label key={m.id} className="flex gap-2"><input type="checkbox" checked={selected.includes(m.id)} onChange={e=>setSelected(e.target.checked?[...selected,m.id]:selected.filter(id=>id!==m.id))}/><span>{m.title}<span className="block text-xs text-gray-500">{new Date(m.started_at).toLocaleString()}</span></span></label>)}</div>
          <p className="font-medium">Recording order — earliest first</p>
          {ordered.map((m,i)=><div className="flex items-center gap-2" key={m.id}><span>{i+1}. {m.title}<span className="block text-xs text-gray-500">{new Date(m.started_at).toLocaleString()}</span></span></div>)}
          <label className="block"><input type="checkbox" checked={audio} onChange={e=>setAudio(e.target.checked)}/> Include audio</label>
        </fieldset>
        <p className="text-xs text-gray-500">Recordings play back to back, without the gap between calls. Generate a new summary and detect speakers for the combined recording. Existing voice profiles remain saved.</p>
        {error&&<p role="alert" className="text-red-700">{error}</p>}
        <div className="flex gap-4"><button className="rounded bg-blue-600 px-3 py-2 text-white disabled:opacity-50" disabled={busy||disabled||selected.length<2||selected.length>10||!title.trim()} onClick={combine}>{busy?'Combining locally…':'Create combined meeting'}</button><button className="meaty-action" disabled={busy} onClick={()=>setOpen(false)}>Cancel</button></div>
      </div>
    </div>}
    {!open&&error&&<p role="alert" className="text-red-700">{error}</p>}
  </div>;
}
