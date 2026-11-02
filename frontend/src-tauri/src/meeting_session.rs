//! Session ownership and reconnect grace, independent of Tauri for testing.
use std::{
    collections::HashSet,
    time::{Duration, Instant},
};
#[derive(Default)]
pub struct Sessions {
    seen: HashSet<String>,
    active: HashSet<String>,
    pending: bool,
    ended_at: Option<Instant>,
}
impl Sessions {
    pub fn update(&mut self, session: &str, joined: bool, now: Instant) {
        if joined {
            if self.seen.insert(session.into()) {
                self.pending = true;
            }
            self.active.insert(session.into());
            self.ended_at = None;
        } else if self.active.remove(session) && self.active.is_empty() {
            self.pending = false;
            self.ended_at = Some(now);
        }
    }
    pub fn action(&mut self, now: Instant) -> &'static str {
        if self
            .ended_at
            .is_some_and(|t| now.duration_since(t) >= Duration::from_secs(8))
        {
            return "stop";
        }
        if std::mem::take(&mut self.pending) {
            "start"
        } else {
            "none"
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stops_after_grace_and_ignores_unknown_end() {
        let mut s = Sessions::default();
        let t = Instant::now();
        s.update("a", true, t);
        assert_eq!(s.action(t), "start");
        s.update("unknown", false, t);
        assert_eq!(s.action(t + Duration::from_secs(9)), "none");
        s.update("a", false, t);
        assert_eq!(s.action(t + Duration::from_secs(7)), "none");
        assert_eq!(s.action(t + Duration::from_secs(8)), "stop");
    }
    #[test]
    fn reconnect_does_not_restart_and_cancels_stop() {
        let mut s = Sessions::default();
        let t = Instant::now();
        s.update("a", true, t);
        s.action(t);
        s.update("a", false, t);
        s.update("a", true, t + Duration::from_secs(3));
        assert_eq!(s.action(t + Duration::from_secs(20)), "none");
    }
    #[test]
    fn waits_for_all_tabs_and_cancels_unconsumed_start() {
        let mut s = Sessions::default();
        let t = Instant::now();
        s.update("a", true, t);
        s.update("b", true, t);
        s.action(t);
        s.update("a", false, t);
        assert_eq!(s.action(t + Duration::from_secs(9)), "none");
        s.update("b", false, t);
        assert_eq!(s.action(t + Duration::from_secs(9)), "stop");
        s.update("c", true, t);
        s.update("c", false, t);
        assert_eq!(s.action(t), "none");
    }
}
