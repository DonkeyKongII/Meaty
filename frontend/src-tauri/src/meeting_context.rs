//! Structured, local calendar context and enrichment queue.
use serde_json::Value;
use std::{io::Write, process::{Command, Stdio}};
use tauri::Manager;

#[tauri::command]
pub async fn meeting_context_action(app: tauri::AppHandle, request: Value) -> Result<Value, String> {
    let script = app.path().resource_dir().map_err(|e| e.to_string())?.join("context_runtime/context.py");
    let db = app.path().app_data_dir().map_err(|e| e.to_string())?.join("meeting_minutes.sqlite");
    tauri::async_runtime::spawn_blocking(move || {
        let mut child = Command::new("/usr/bin/python3").arg(script).arg("--db").arg(db)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().map_err(|e| e.to_string())?;
        child.stdin.take().ok_or("Missing worker input")?.write_all(&serde_json::to_vec(&request).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        let output = child.wait_with_output().map_err(|e| e.to_string())?;
        let value: Value = serde_json::from_slice(&output.stdout).map_err(|_| "Meeting context worker failed".to_string())?;
        if !output.status.success() { return Err(value["error"].as_str().unwrap_or("Context failed").to_string()); }
        Ok(value)
    }).await.map_err(|e| e.to_string())?
}
