export interface SpeakerAnalysis {
  model:string;
  segments:{start:number;end:number;speaker:string}[];
  speakers:{id:string;name:string;clean_seconds:number;can_enroll:boolean;mixed?:boolean;sample_path:string|null;profile_id:string|null;status:'unknown'|'recognized'|'manual';score:number|null}[];
  profiles:{id:string;name:string}[];
}

// Mark transcript chunks with all materially overlapping voices. A chunk spanning
// a turn change must not falsely attribute the entire sentence to one person.
export function speakerLabel(data:SpeakerAnalysis|null,start:number,end?:number):string|undefined {
  if(!data||!Number.isFinite(start))return undefined;
  const stop=end!==undefined&&end>start?end:start+0.5;
  const overlap=new Map<string,number>();
  for(const turn of data.segments){
    const duration=Math.min(stop,turn.end)-Math.max(start,turn.start);
    if(duration>0)overlap.set(turn.speaker,(overlap.get(turn.speaker)||0)+duration);
  }
  const maximum=Math.max(0,...overlap.values());
  if(!maximum)return undefined;
  const ids=[...overlap].filter(([,duration])=>duration>=Math.min(0.25,maximum)&&duration>=maximum*0.2).map(([id])=>id);
  const names=ids.map(id=>data.speakers.find(s=>s.id===id)?.name||'Unknown speaker');
  return names.join(' / ');
}
