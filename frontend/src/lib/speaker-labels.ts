export type SpeakerTag={id:string;name:string;sourceId?:string;start?:number;end?:number;canRemove?:boolean};
export interface SpeakerAnalysis {
  speaker_tag_exclusions?:{start:number;end:number;speaker:string}[];
  job_status?:string; job_error?:string; participant_count?:number;
  profile_count?:number;
  learning_notice?:string;
  model:string;
  requested_speakers?:number;
  analysis_warning?:string|null;
  unassigned_seconds?:number;
  segments:{start:number;end:number;speaker:string}[];
  speakers:{id:string;name:string;clean_seconds:number;can_enroll:boolean;mixed?:boolean;sample_path:string|null;profile_id:string|null;status:'unknown'|'recognized'|'manual';score:number|null}[];
  profiles:{id:string;name:string}[];
}

// Mark transcript chunks with all materially overlapping voices. A chunk spanning
// a turn change must not falsely attribute the entire sentence to one person.
export function speakerLabel(data:SpeakerAnalysis|null,start:number,end?:number):string|undefined {
  if(!data||data.analysis_warning||!Number.isFinite(start))return undefined;
  const stop=end!==undefined&&end>start?end:start+0.5;
  const overlap=new Map<string,number>();
  for(const turn of data.segments){
    const duration=Math.min(stop,turn.end)-Math.max(start,turn.start);
    if(duration>0&&!data.speaker_tag_exclusions?.some(x=>x.speaker===turn.speaker&&x.start===start&&x.end===stop))overlap.set(turn.speaker,(overlap.get(turn.speaker)||0)+duration);
  }
  const maximum=Math.max(0,...overlap.values());
  if(!maximum)return undefined;
  const ids=[...overlap].filter(([,duration])=>duration>=Math.min(0.25,maximum)&&duration>=maximum*0.2).map(([id])=>id);
  const names=ids.map(id=>data.speakers.find(s=>s.id===id)?.name||'Unassigned speech');
  return names.join(' / ');
}

export function speakerTags(data:SpeakerAnalysis|null,start:number,end?:number):SpeakerTag[] {
 if(!Number.isFinite(start))return [];
 const stop=end!==undefined&&end>start?end:start+0.5;
 const span={id:`__span__:${start}:${stop}`,name:'Unidentified speaker'};
 if(!data||data.analysis_warning)return [span];
 const overlap=new Map<string,number>();
 for(const turn of data.segments){const duration=Math.min(stop,turn.end)-Math.max(start,turn.start);if(duration>0&&!data.speaker_tag_exclusions?.some(x=>x.speaker===turn.speaker&&x.start===start&&x.end===stop))overlap.set(turn.speaker,(overlap.get(turn.speaker)||0)+duration);}
 const max=Math.max(0,...overlap.values());if(!max)return [span];
 const ids=[...overlap].filter(([,n])=>n>=Math.min(.25,max)&&n>=max*.2).map(([id])=>id);
 const hasKnown=ids.some(id=>{const voice=data.speakers.find(s=>s.id===id);return voice&&voice.status!=='unknown';});
 return ids.map(id=>{
  const voice=data.speakers.find(s=>s.id===id);
  return {id:voice?id:span.id,sourceId:id,name:!voice||voice.status==='unknown'?'Unidentified speaker':voice.name,start,end:stop,canRemove:ids.length>1&&hasKnown&&(!voice||voice.status==='unknown')};
 });
}

// A person may own several diarization labels. Keep unresolved voices separate.
export function groupedSpeakers(data: SpeakerAnalysis | null) {
  const known = new Map<string, SpeakerAnalysis['speakers']>();
  const unresolved: SpeakerAnalysis['speakers'] = [];
  for (const speaker of data?.speakers ?? []) {
    if (speaker.status === 'unknown') { unresolved.push(speaker); continue; }
    const key = speaker.profile_id || speaker.name.trim().toLocaleLowerCase();
    known.set(key, [...(known.get(key) ?? []), speaker]);
  }
  return { known: [...known.values()], unresolved };
}
