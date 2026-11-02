//! Offline speaker analysis; recording and transcription remain independent.
use crate::state::AppState;
use serde_json::{json, Value};
use std::{
    io::Write,
    process::{Command, Stdio},
};
use tauri::Manager;
static WORKER_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[tauri::command]
pub async fn speaker_action(
    app: tauri::AppHandle,
    state: tauri::State<'_, AppState>,
    meeting_id: String,
    action: String,
    speaker_id: Option<String>,
    profile_id: Option<String>,
    name: Option<String>,
    num_speakers: Option<i32>,
    force: Option<bool>,
) -> Result<Value, String> {
    if !["get", "analyze", "enroll", "label", "rename", "forget"].contains(&action.as_str()) {
        return Err("Unsupported speaker action".into());
    }
    if action == "analyze" && crate::is_recording().await {
        return Err("Finish recording before analyzing speakers.".into());
    }
    let count = num_speakers.unwrap_or(-1);
    if count != -1 && !(1..=20).contains(&count) {
        return Err("Choose automatic speaker count or a number from 1 to 20.".into());
    }
    let root = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("speaker-recognition");
    let python = root.join("venv/bin/python3");
    if !python.is_file() {
        return Err("Speaker recognition is not installed. Run integrations/speakers/setup.py from the source checkout.".into());
    }
    let script = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("speaker_runtime/worker.py");
    let mut request = json!({"root":root,"meeting_id":meeting_id,"action":action,"speaker_id":speaker_id,"profile_id":profile_id,"name":name,"num_speakers":count,"force":force.unwrap_or(false)});
    if action == "analyze" {
        let folder: Option<String> =
            sqlx::query_scalar("SELECT folder_path FROM meetings WHERE id=?")
                .bind(&meeting_id)
                .fetch_optional(state.db_manager.pool())
                .await
                .map_err(|e| e.to_string())?
                .flatten();
        let folder =
            std::path::PathBuf::from(folder.ok_or("This meeting has no saved recording folder.")?);
        let audio = [
            "audio.mp4",
            "audio.wav",
            "audio.m4a",
            "audio.mp3",
            "recording.wav",
        ]
        .iter()
        .map(|file| folder.join(file))
        .find(|path| path.is_file())
        .or_else(|| {
            std::fs::read_dir(&folder)
                .ok()?
                .filter_map(Result::ok)
                .map(|e| e.path())
                .find(|p| {
                    p.extension()
                        .and_then(|e| e.to_str())
                        .is_some_and(|e| ["wav", "mp4", "m4a", "mp3", "flac"].contains(&e))
                })
        })
        .ok_or("No saved audio found in this meeting folder.")?;
        let ffmpeg = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .ok_or("Missing app directory")?
            .join("ffmpeg");
        request["audio"] = json!(audio);
        request["ffmpeg"] = json!(ffmpeg);
    }
    // One worker at a time avoids simultaneous model loads and profile writes.
    let _guard = WORKER_LOCK.lock().await;
    if action == "analyze" && crate::is_recording().await {
        return Err("Finish recording before analyzing speakers.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let mut child = Command::new(python)
            .arg(script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Could not start speaker analysis: {e}"))?;
        let payload = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
        child
            .stdin
            .take()
            .ok_or("Missing worker input")?
            .write_all(&payload)
            .map_err(|e| e.to_string())?;
        let output = child.wait_with_output().map_err(|e| e.to_string())?;
        let value: Value = serde_json::from_slice(&output.stdout).map_err(|_| {
            format!(
                "Speaker worker failed: {}",
                String::from_utf8_lossy(&output.stderr)
                    .chars()
                    .take(1000)
                    .collect::<String>()
            )
        })?;
        if !output.status.success() {
            return Err(value["error"]
                .as_str()
                .unwrap_or("Speaker analysis failed")
                .to_owned());
        }
        Ok(value)
    })
    .await
    .map_err(|e| e.to_string())?
}
