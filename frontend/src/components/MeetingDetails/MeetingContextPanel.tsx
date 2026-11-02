'use client';
import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';

type Context = { classification: string; companies: {domain:string;name:string}[]; participants: {name:string;email:string;attendance:string}[]; status:string; calendar_title?:string; notes?:string; identity_suggestions?:{name:string;start?:number;reason:string}[] };
export function MeetingContextPanel({meetingId}: {meetingId:string}) {
  const [data,setData] = useState<Context|null>(null);
  const [editing,setEditing] = useState(false);
  const [people,setPeople] = useState('');
  const [domains,setDomains] = useState('');
  const [aliases,setAliases] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const {refetchMeetings} = useSidebar();
  const call = (request:object) => invoke<any>('meeting_context_action',{request});
  useEffect(()=>{
    let active=true;
    const load=()=>call({action:'get',meeting_id:meetingId}).then(value=>{if(active)setData(value);}).catch(e=>{if(active)setError(String(e));});
    setData(null); setEditing(false); setError(''); load();
    const timer=setInterval(load,15000);
    return()=>{active=false;clearInterval(timer);};
  },[meetingId]);
  async function edit() {
    try {
      const settings=await call({action:'settings'});
      setDomains(settings.internal_domains.join(', '));
      setAliases(Object.entries(settings.company_names).map(([d,n])=>`${d} = ${n}`).join('\n'));
      setPeople(data?.participants.map(p=>`${p.name} <${p.email}>${p.attendance==='confirmed'?' confirmed':''}`).join('\n')??'');
      setEditing(true);
    } catch(e){setError(String(e));}
  }
  async function save() {
    setBusy(true);setError('');
    try {
      const company_names=Object.fromEntries(aliases.split('\n').filter(l=>l.trim()).map(l=>{const i=l.indexOf('=');if(i<1)throw Error('Use domain = Company Name');return [l.slice(0,i).trim().toLowerCase(),l.slice(i+1).trim()];}));
      const participants=people.split('\n').filter(l=>l.trim()).map(l=>{
        const match=l.trim().match(/^(.*?)\s*<([^>]*)>\s*(confirmed)?$/);
        if(!match)throw Error('Use Name <email@example.com> on each line. Add confirmed only for known attendees.');
        return {name:match[1],email:match[2],attendance:match[3]?'confirmed':'invited'};
      });
      await call({action:'settings',data:{internal_domains:domains.split(',').map(d=>d.trim()).filter(Boolean),company_names}});
      setData(await call({action:'save',meeting_id:meetingId,data:{...data,participants}}));
      setEditing(false);await refetchMeetings();
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function queue(){setBusy(true);try{setData(await call({action:'queue',meeting_id:meetingId}));}catch(e){setError(String(e));}finally{setBusy(false);}}
  return <div className="border-b p-3 text-sm space-y-2">
    <div className="flex items-center gap-3"><strong>People & companies</strong><span>{data?.classification==='internal'?'Internal':data?.companies?.map(c=>c.name).join(', ')||'Unclassified'}</span><button className="text-blue-600 ml-auto" onClick={edit}>Edit</button></div>
    {data?.calendar_title&&<div>{data.calendar_title}</div>}
    <div className="text-gray-600">{data?.participants?.length||0} expected participants · {data?.participants?.filter(p=>p.attendance==='confirmed').length||0} confirmed attendees</div>
    <details className="text-xs"><summary className="cursor-pointer text-gray-600">Participants & evidence{data?.identity_suggestions?.length ? ` · ${data.identity_suggestions.length} identity suggestions` : ''}</summary><div className="space-y-2 max-h-48 overflow-y-auto mt-2">
    {!!data?.participants?.length&&<div>{data.participants.map(p=>`${p.name||p.email}${p.attendance==='confirmed'?' (confirmed)':''}`).join(', ')}</div>}
    {!!data?.identity_suggestions?.length&&<div className="text-xs"><strong>Suggested identities — review in Speakers</strong>{data.identity_suggestions.map((s,i)=><p key={i}>{s.name}{s.start!=null?` at ${Math.floor(s.start/60)}:${String(Math.floor(s.start%60)).padStart(2,'0')}`:''}: {s.reason}</p>)}</div>}
    {data?.notes&&<p className="text-xs text-gray-500">{data.notes}</p>}
    </div></details>
    <div className="flex gap-3 text-xs text-gray-500"><span>Calendar enrichment: {data?.status?.replaceAll('_',' ')||'loading'}</span><button disabled={busy} onClick={queue} className="text-blue-600">Request calendar lookup</button></div>
    {editing&&<div className="space-y-2 max-h-64 overflow-y-auto">
      <label className="block">Participants — one Name &lt;email&gt; per line; add “confirmed” for known attendees<textarea className="border rounded w-full p-2" rows={5} value={people} onChange={e=>setPeople(e.target.value)}/></label>
      <label className="block">Internal email domains<input className="border rounded w-full p-2" value={domains} onChange={e=>setDomains(e.target.value)}/></label>
      <label className="block">Company names — domain = Company Name<textarea className="border rounded w-full p-2" rows={3} value={aliases} onChange={e=>setAliases(e.target.value)}/></label>
      <button disabled={busy} className="text-blue-600 mr-3" onClick={save}>Save</button><button onClick={()=>setEditing(false)}>Cancel</button>
    </div>}
    {error&&<p role="alert" className="text-red-600">{error}</p>}
  </div>;
}
