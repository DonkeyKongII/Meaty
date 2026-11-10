//! Structured, local calendar context and enrichment queue.
use serde_json::Value;
use std::{
    io::Write,
    process::{Command, Stdio},
};
use tauri::Manager;

#[tauri::command]
pub async fn meeting_context_action(
    app: tauri::AppHandle,
    request: Value,
) -> Result<Value, String> {
    run_context(&app,request).await
}
pub async fn run_context<R:tauri::Runtime>(app:&tauri::AppHandle<R>,mut request:Value)->Result<Value,String> {
    if request["action"] == "live" {return Ok(crate::live_meeting::snapshot(&app));}
    if request["action"] == "get" && request["meeting_id"].as_str().is_some_and(|id|id.starts_with("live-")) {
        let snapshot=crate::live_meeting::snapshot(&app);
        return if snapshot["live_id"]==request["meeting_id"] {Ok(snapshot)} else {Err("This recording has ended".into())};
    }
    if request["action"] == "combine" {
        if crate::audio::recording_commands::is_recording().await {
            return Err("Finish recording before combining meetings".into());
        }
        let executable = std::env::current_exe().map_err(|e| e.to_string())?;
        request["ffmpeg_path"] = Value::String(
            executable
                .parent()
                .ok_or("Missing app directory")?
                .join("ffmpeg")
                .to_string_lossy()
                .into_owned(),
        );
    }
    let script = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("context_runtime/context.py");
    let db = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("meeting_minutes.sqlite");
    let combined=request["action"] == "combine" && request["include_audio"] != false;
    let value=tauri::async_runtime::spawn_blocking(move || {
        let mut child = Command::new("/usr/bin/python3")
            .arg(script)
            .arg("--db")
            .arg(db)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| e.to_string())?;
        child
            .stdin
            .take()
            .ok_or("Missing worker input")?
            .write_all(&serde_json::to_vec(&request).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        let output = child.wait_with_output().map_err(|e| e.to_string())?;
        let value: Value = serde_json::from_slice(&output.stdout)
            .map_err(|_| "Meeting context worker failed".to_string())?;
        if !output.status.success() {
            return Err(value["error"]
                .as_str()
                .unwrap_or("Context failed")
                .to_string());
        }
        Ok(value)
    })
    .await
    .map_err(|e| e.to_string())??;
    if combined {if let Some(id)=value["id"].as_str() {crate::speakers::enqueue(&app,id,None).await?;}}
    Ok(value)
}
