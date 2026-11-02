//! Local-only bridge for the Chrome Google Meet companion extension.
use std::sync::Mutex;
#[path = "meeting_session.rs"]
mod meeting_session;
static STATE: Mutex<Option<meeting_session::Sessions>> = Mutex::new(None);

#[tauri::command]
pub fn take_meeting_autostart() -> String {
    let mut state = STATE.lock().unwrap_or_else(|e| e.into_inner());
    state
        .get_or_insert_with(Default::default)
        .action(std::time::Instant::now())
        .into()
}

#[cfg(target_os = "macos")]
pub fn start<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
) -> Result<(), Box<dyn std::error::Error>> {
    use std::{
        io::{BufRead, BufReader, Write},
        os::unix::{fs::PermissionsExt, net::UnixListener},
        time::Duration,
    };
    use tauri::Manager;
    let directory = app.path().app_data_dir()?;
    std::fs::create_dir_all(&directory)?;
    let path = directory.join("meeting-autostart.sock");
    // A live instance owns its socket. Never unlink it out from under that instance.
    if std::os::unix::net::UnixStream::connect(&path).is_ok() {
        return Err("Meeting bridge already running".into());
    }
    if path.exists() {
        std::fs::remove_file(&path)?;
    }
    let listener = UnixListener::bind(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    std::thread::spawn(move || {
        for connection in listener.incoming() {
            let Ok(mut stream) = connection else { continue };
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
            let mut line = String::new();
            let read = BufReader::new(std::io::Read::take(&mut stream, 4096)).read_line(&mut line);
            let accepted = read.is_ok()
                && serde_json::from_str::<serde_json::Value>(&line)
                    .ok()
                    .is_some_and(|message| {
                        let Some(session) = message["session"].as_str() else {
                            return false;
                        };
                        if (message["event"] != "joined" && message["event"] != "ended")
                            || message["provider"] != "google-meet"
                            || session.is_empty()
                            || session.len() > 128
                        {
                            return false;
                        }
                        let mut state = STATE.lock().unwrap_or_else(|e| e.into_inner());
                        state.get_or_insert_with(Default::default).update(
                            session,
                            message["event"] == "joined",
                            std::time::Instant::now(),
                        );
                        true
                    });
            let _ = writeln!(stream, "{{\"accepted\":{accepted}}}");
        }
    });
    Ok(())
}
