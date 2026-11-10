'use client';
import {useEffect,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
export function CompanySettings(){
 const [domains,setDomains]=useState(''),[aliases,setAliases]=useState(''),[busy,setBusy]=useState(true),[error,setError]=useState(''),[saved,setSaved]=useState(false);
 useEffect(()=>{let active=true;invoke<{internal_domains:string[];company_names:Record<string,string>}>('meeting_context_action',{request:{action:'settings'}}).then(v=>{if(active){setDomains(v.internal_domains.join(', '));setAliases(Object.entries(v.company_names).map(([d,n])=>`${d} = ${n}`).join('\n'));}}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setBusy(false);});return()=>{active=false;};},[]);
 async function save(){setBusy(true);setError('');setSaved(false);try{
  const company_names=Object.fromEntries(aliases.split('\n').filter(l=>l.trim()).map(l=>{const i=l.indexOf('=');if(i<1||!l.slice(i+1).trim())throw Error('Use domain = Company Name');return[l.slice(0,i).trim().toLowerCase(),l.slice(i+1).trim()];}));
  await invoke('meeting_context_action',{request:{action:'settings',data:{internal_domains:domains.split(',').map(d=>d.trim()).filter(Boolean),company_names}}});setSaved(true);
 }catch(e){setError(String(e));}finally{setBusy(false);}}
 return <section className="space-y-4 border-t pt-6"><h2 className="text-lg font-semibold">People & companies</h2><fieldset disabled={busy} className="space-y-4"><label className="block text-sm">Internal email domains<input className="mt-2 w-full border p-2" value={domains} onChange={e=>setDomains(e.target.value)} placeholder="company.com, example.com"/></label><label className="block text-sm">Company names<textarea className="mt-2 w-full border p-2" rows={4} value={aliases} onChange={e=>setAliases(e.target.value)} placeholder="snowflake.com = Snowflake"/></label><button className="meaty-action" onClick={save}>{busy?'Saving…':'Save company settings'}</button></fieldset>{saved&&<p role="status">Saved for all meetings.</p>}{error&&<p role="alert">{error}</p>}</section>;
}
