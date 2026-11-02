//! Summary attribution uses saved timed assignments, never calendar invitees.
use std::collections::HashMap;
pub struct Turn { pub start:f64, pub end:f64, pub speaker:String }
pub struct Line { pub start:Option<f64>, pub end:Option<f64>, pub text:String }
pub fn annotate(text:&str, lines:&[Line], turns:&[Turn], names:&HashMap<String,String>) -> String {
    let mut labels:HashMap<String,Option<String>>=HashMap::new();
    for line in lines {
        let Some(start)=line.start.filter(|v|v.is_finite()&&*v>=0.0) else {continue};
        let end=line.end.filter(|v|v.is_finite()&&*v>start).unwrap_or(start+0.5);
        let mut overlap:HashMap<&str,f64>=HashMap::new();
        for turn in turns {
            let duration=end.min(turn.end)-start.max(turn.start);
            if duration>0.0 {*overlap.entry(&turn.speaker).or_default()+=duration;}
        }
        let max=overlap.values().copied().fold(0.0,f64::max);
        if max<=0.0 {continue}
        // Keep turn order stable and include every materially overlapping voice.
        let mut ids:Vec<&str>=turns.iter().map(|t|t.speaker.as_str()).filter(|id|overlap.get(id).is_some_and(|v|*v>=0.25_f64.min(max)&&*v>=max*0.2)).collect();
        ids.dedup();let mut seen=std::collections::HashSet::new();ids.retain(|id|seen.insert(*id));
        let label=ids.iter().map(|id|names.get(*id).map(String::as_str).unwrap_or("Unassigned speech")).collect::<Vec<_>>().join(" / ");
        let secs=start.floor() as u64;
        let key=format!("[{:02}:{:02}] {}",secs/60,secs%60,line.text);
        labels.entry(key).and_modify(|old|{if old.as_ref()!=Some(&label){*old=None}}).or_insert(Some(label));
    }
    text.lines().map(|line|{
        if let Some(Some(label))=labels.get(line) {
            // Quotes/newlines in names cannot break the line structure.
            let label=label.replace(['\n','\r']," ");
            if let Some((time,body))=line.split_once(' ') {return format!("{time} [Speaker: {label}] {body}")}
        }
        line.to_owned()
    }).collect::<Vec<_>>().join("\n")
}
#[cfg(test)] mod tests {
 use super::*;
 fn line(start:Option<f64>,end:Option<f64>,text:&str)->Line{Line{start,end,text:text.into()}}
 fn turn(start:f64,end:f64,id:&str)->Turn{Turn{start,end,speaker:id.into()}}
 #[test] fn names_and_mixed_turns(){let names=HashMap::from([("a".into(),"Ian".into()),("b".into(),"Mukul".into())]);let turns=vec![turn(0.0,2.0,"a"),turn(2.0,4.0,"b")];let text=annotate("[00:00] I will send it.",&[line(Some(0.0),Some(4.0),"I will send it.")],&turns,&names);assert_eq!(text,"[00:00] [Speaker: Ian / Mukul] I will send it.");}
 #[test] fn preserve_unknown_and_edited_text(){let names=HashMap::new();assert_eq!(annotate("[00:00] Edited",&[line(Some(0.0),Some(1.0),"Original")],&[turn(0.0,1.0,"a")],&names),"[00:00] Edited");assert_eq!(annotate("[00:00] Original",&[line(None,None,"Original")],&[turn(0.0,1.0,"a")],&names),"[00:00] Original");}
 #[test] fn unassigned_is_not_a_new_person(){assert_eq!(annotate("[00:01] Hello",&[line(Some(1.0),Some(2.0),"Hello")],&[turn(1.0,2.0,"__unassigned__")],&HashMap::new()),"[00:01] [Speaker: Unassigned speech] Hello");}
 #[test] fn conflicting_duplicate_is_not_attributed(){let names=HashMap::from([("a".into(),"Ian".into()),("b".into(),"Mukul".into())]);assert_eq!(annotate("[00:00] Yes",&[line(Some(0.0),Some(0.3),"Yes"),line(Some(0.6),Some(0.9),"Yes")],&[turn(0.0,0.3,"a"),turn(0.6,0.9,"b")],&names),"[00:00] Yes");}
}
