//! Session ownership and reconnect grace, independent of Tauri for testing.
use std::{
    collections::{HashMap, HashSet},
    time::{Duration, Instant},
};

/// Grace period after the last session ends before "stop" is returned, so a
/// brief reconnect does not bounce the recording.
const STOP_GRACE: Duration = Duration::from_secs(8);

/// A session with no bridge message (joined/participants heartbeat) for this
/// long is treated as ended: the tab crashed, Chrome restarted, or the user
/// navigated away in a way that never delivered an "ended".
const HEARTBEAT_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Default)]
pub struct Sessions {
    seen: HashSet<String>,
    /// Active sessions with the time of their last bridge message (heartbeat).
    active: HashMap<String, Instant>,
    pending: bool,
    ended_at: Option<Instant>,
    /// A "stop" action was consumed by the frontend. A rejoin after this point
    /// must restart recording, even for an already-seen session.
    stop_fired: bool,
}
impl Sessions {
    /// Record a bridge message. `joined` covers both the extension's "joined"
    /// event and its "participants" heartbeat: a heartbeat for a session the
    /// app does not know (e.g. the app restarted mid-call) must auto-start
    /// exactly like a join, or auto-start would be starved for the whole call.
    pub fn update(&mut self, session: &str, joined: bool, now: Instant) {
        if joined {
            if self.seen.insert(session.into()) || self.stop_fired {
                self.pending = true;
            }
            self.stop_fired = false;
            self.active.insert(session.into(), now);
            self.ended_at = None;
        } else if self.active.remove(session).is_some() && self.active.is_empty() {
            self.pending = false;
            self.ended_at = Some(now);
        }
    }
    /// Expire sessions whose heartbeat has gone silent. The meeting is
    /// considered ended when the last heartbeat was due, not when we happened
    /// to notice, so the stop grace is not extended by polling cadence.
    fn expire_stale(&mut self, now: Instant) {
        let before = self.active.len();
        let mut last_gone: Option<Instant> = None;
        self.active.retain(|_, last| {
            let alive = now.duration_since(*last) < HEARTBEAT_TIMEOUT;
            if !alive {
                last_gone = last_gone.max(Some(*last));
            }
            alive
        });
        if before > 0 && self.active.is_empty() {
            self.pending = false;
            self.ended_at = last_gone.map(|t| t + HEARTBEAT_TIMEOUT).or(Some(now));
        }
    }
    pub fn action(&mut self, now: Instant) -> &'static str {
        self.expire_stale(now);
        if self
            .ended_at
            .is_some_and(|t| now.duration_since(t) >= STOP_GRACE)
        {
            self.stop_fired = true;
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
    fn rejoin_after_stop_restarts() {
        let mut s = Sessions::default();
        let t = Instant::now();
        s.update("a", true, t);
        s.action(t);
        s.update("a", false, t);
        assert_eq!(s.action(t + Duration::from_secs(8)), "stop");
        // Rejoin after the stop was consumed: recording must restart even
        // though the session was already seen.
        s.update("a", true, t + Duration::from_secs(9));
        assert_eq!(s.action(t + Duration::from_secs(9)), "start");
        assert_eq!(s.action(t + Duration::from_secs(10)), "none");
    }
    #[test]
    fn participants_heartbeat_for_unknown_session_joins() {
        // App restarted mid-call: the extension keeps sending "participants"
        // (joined=true at this layer); the unknown session must auto-start.
        let mut s = Sessions::default();
        let t = Instant::now();
        s.update("a", true, t);
        s.action(t);
        s.update("a", false, t);
        assert_eq!(s.action(t + Duration::from_secs(8)), "stop");
        let mut fresh = Sessions::default();
        fresh.update("a", true, t);
        assert_eq!(fresh.action(t), "start");
    }
    #[test]
    fn silent_session_expires_and_stops() {
        let mut s = Sessions::default();
        let t = Instant::now();
        s.update("a", true, t);
        s.action(t);
        // Heartbeats keep the session alive past the timeout.
        s.update("a", true, t + Duration::from_secs(50));
        assert_eq!(s.action(t + Duration::from_secs(100)), "none");
        // Silence longer than the heartbeat timeout + stop grace ends it.
        assert_eq!(
            s.action(t + Duration::from_secs(50 + 60 + 8)),
            "stop"
        );
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
        s.update("c", true, t + Duration::from_secs(10));
        s.update("c", false, t + Duration::from_secs(10));
        assert_eq!(s.action(t + Duration::from_secs(10)), "none");
    }
}
