use std::{collections::HashMap, time::{Duration,Instant}};
#[derive(Default)]
pub struct Counts { recording:bool, peak:u64, sessions:HashMap<String,(u64,Instant)> }
impl Counts {
    pub fn begin(&mut self, now:Instant) {
        self.recording=true;
        self.peak=self.sessions.values().filter(|(_,t)|now.duration_since(*t)<Duration::from_secs(15)).map(|(n,_)|*n).max().unwrap_or(0);
    }
    pub fn observe(&mut self, session:&str, count:u64, now:Instant) {
        if !(1..=100).contains(&count) {return}
        self.sessions.insert(session.into(),(count,now));
        if self.recording {self.peak=self.peak.max(count)}
    }
    pub fn end_session(&mut self, session:&str) {self.sessions.remove(session);}
    pub fn finish(&mut self)->Option<u64> {
        self.recording=false; let count=std::mem::take(&mut self.peak);if count>0 {Some(count)} else {None}
    }
}
#[cfg(test)] mod tests {
 use super::*;
 #[test] fn retains_peak_when_attendees_leave() {let mut c=Counts::default();let t=Instant::now();c.observe("a",2,t);c.begin(t);c.observe("a",8,t);c.observe("a",3,t);c.end_session("a");assert_eq!(c.finish(),Some(8));}
 #[test] fn resets_between_recordings() {let mut c=Counts::default();let t=Instant::now();c.begin(t);c.observe("a",8,t);c.finish();c.end_session("a");c.begin(t);c.observe("b",2,t);assert_eq!(c.finish(),Some(2));}
 #[test] fn stale_and_invalid_samples_do_not_supply_count() {let mut c=Counts::default();let t=Instant::now();c.observe("a",8,t);c.begin(t+Duration::from_secs(16));c.observe("a",0,t);c.observe("a",101,t);assert_eq!(c.finish(),None);}
}
