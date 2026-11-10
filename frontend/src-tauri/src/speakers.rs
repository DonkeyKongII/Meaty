//! Offline speaker analysis; recording and transcription remain independent.
use crate::state::AppState;
use serde_json::{json, Value};
use std::{
    io::Write,
    process::{Command, Stdio},
};
use tauri::{Manager, Emitter};
static LIVE_LABEL_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
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
    query: Option<String>,
    offset: Option<i64>,
    remember: Option<bool>,
) -> Result<Value, String> {
    let _live_guard=if meeting_id.starts_with("live-") {Some(LIVE_LABEL_LOCK.lock().await)} else {None};
    if !["get", "analyze", "enroll", "label", "rename", "forget", "search", "assign", "remove_tag"].contains(&action.as_str()) {
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
    let mut request = json!({"root":root,"meeting_id":meeting_id,"action":action,"speaker_id":speaker_id,"profile_id":profile_id,"name":name,"num_speakers":count,"force":force.unwrap_or(false),"query":query.unwrap_or_default(),"offset":offset.unwrap_or(0),"remember":remember.unwrap_or(true)});
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
    // Reads and labels must stay responsive while a model is running.
    let _guard = if action == "analyze" {Some(WORKER_LOCK.lock().await)} else {None};
    if action == "analyze" && crate::is_recording().await {
        return Err("Finish recording before analyzing speakers.".into());
    }
    let action_done=action.clone();
    let id_done=meeting_id.clone();
    let mut result=tauri::async_runtime::spawn_blocking(move || {
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
    .map_err(|e| e.to_string())??;
    let pool=state.db_manager.pool();
    jobs(pool).await?;
    if action_done == "analyze" {
        sqlx::query("UPDATE speaker_jobs SET status='complete',error=NULL WHERE meeting_id=?").bind(&id_done).execute(pool).await.map_err(|e|e.to_string())?;
    }
    if let Some((status,count,error))=sqlx::query_as::<_,(String,Option<i64>,Option<String>)>("SELECT status,participant_count,error FROM speaker_jobs WHERE meeting_id=?")
        .bind(&id_done).fetch_optional(pool).await.map_err(|e|e.to_string())? {
        result["job_status"]=json!(status); result["participant_count"]=json!(count);result["job_error"]=json!(error);
    }
    Ok(result)
}

/// Snapshot speaker names at summary start. Only labels/timing enter the prompt.
pub async fn summary_text(root: &std::path::Path, pool: &sqlx::SqlitePool, meeting_id: &str, text: &str) -> Result<String,String> {
    use sha2::{Digest,Sha256};
    use sqlx::{Connection, sqlite::SqliteConnectOptions};
    use crate::summary::speaker_context::{annotate,Line,Turn};
    let path=root.join("speaker-recognition/voices.sqlite");
    if !path.is_file(){return Ok(text.to_owned())}
    let options=SqliteConnectOptions::new().filename(path).read_only(true);
    let mut db=sqlx::SqliteConnection::connect_with(&options).await.map_err(|e|e.to_string())?;
    let key=format!("{:x}",Sha256::digest(meeting_id.as_bytes()));
    let data:Option<String>=sqlx::query_scalar("SELECT data FROM meetings WHERE id=?").bind(key).fetch_optional(&mut db).await.map_err(|e|e.to_string())?;
    let Some(data)=data else{return Ok(text.to_owned())};
    let data:Value=serde_json::from_str(&data).map_err(|e|e.to_string())?;
    let speakers=data["speakers"].as_array().ok_or("Invalid saved speaker analysis")?;
    let expected=data["requested_speakers"].as_i64().unwrap_or(-1);
    let limit=if expected>0 && data["count_is_estimate"]!=true{expected as usize}else{20};
    if speakers.iter().filter(|s|!s["id"].as_str().unwrap_or("").starts_with("manual-")).count()>limit || data["analysis_warning"].as_str().is_some(){return Ok(text.to_owned())}
    let profiles:Vec<(String,String)>=sqlx::query_as("SELECT id,name FROM profiles").fetch_all(&mut db).await.map_err(|e|e.to_string())?;
    let profiles:std::collections::HashMap<_,_>=profiles.into_iter().collect();
    let names=speakers.iter().filter_map(|s|{
        let id=s["id"].as_str()?;
        let name=s["profile_id"].as_str().and_then(|id|profiles.get(id).map(String::as_str)).or_else(||s["name"].as_str())?;
        Some((id.to_owned(),name.to_owned()))
    }).collect();
    let turns=data["segments"].as_array().ok_or("Invalid saved speaker turns")?.iter().filter_map(|t|Some(Turn{start:t["start"].as_f64()?,end:t["end"].as_f64()?,speaker:t["speaker"].as_str()?.to_owned()})).collect::<Vec<_>>();
    let rows:Vec<(Option<f64>,Option<f64>,String)>=sqlx::query_as("SELECT audio_start_time,audio_end_time,transcript FROM transcripts WHERE meeting_id=?").bind(meeting_id).fetch_all(pool).await.map_err(|e|e.to_string())?;
    let lines=rows.into_iter().map(|(start,end,text)|Line{start,end,text}).collect::<Vec<_>>();
    Ok(annotate(text,&lines,&turns,&names))
}

// Durable queue: saved meetings finish analysis even after a restart or navigation.
pub(crate) async fn jobs(pool: &sqlx::SqlitePool) -> Result<(),String> {
    sqlx::query("CREATE TABLE IF NOT EXISTS speaker_jobs (meeting_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'queued', participant_count INTEGER, error TEXT)")
        .execute(pool).await.map_err(|e|e.to_string())?; Ok(())
}
pub async fn enqueue<R: tauri::Runtime>(app: &tauri::AppHandle<R>, id: &str, count: Option<u64>) -> Result<(),String> {
    let state=app.state::<AppState>(); let pool=state.db_manager.pool(); jobs(pool).await?;
    sqlx::query("INSERT OR IGNORE INTO speaker_jobs(meeting_id,participant_count) VALUES(?,?)")
        .bind(id).bind(count.map(|v|v as i64)).execute(pool).await.map_err(|e|e.to_string())?; Ok(())
}

pub fn start_background(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut initialized=false;
        loop {
            tokio::time::sleep(std::time::Duration::from_secs(5)).await;
            let Some(state)=app.try_state::<AppState>() else {continue};
            let pool=state.db_manager.pool();
            if jobs(pool).await.is_err() {continue}
            if !initialized {
                let _=sqlx::query("UPDATE speaker_jobs SET status='queued' WHERE status='running'").execute(pool).await;
                // Backfill missing analyses from recordings saved by older builds.
                // Existing named analyses are marked complete and never re-detected.
                if let Ok(ids)=sqlx::query_scalar::<_,String>("SELECT id FROM meetings WHERE folder_path IS NOT NULL AND id NOT IN (SELECT meeting_id FROM speaker_jobs)").fetch_all(pool).await {
                    for id in ids {
                        let saved=speaker_action(app.clone(),app.state::<AppState>(),id.clone(),"get".into(),None,None,None,None,None,None,None,None).await;
                        let complete=saved.as_ref().is_ok_and(|v|v["segments"].as_array().is_some_and(|s|!s.is_empty()) && v["speakers"].as_array().is_some_and(|s|s.iter().any(|v|!v["id"].as_str().unwrap_or("").starts_with("manual-"))) && v["analysis_warning"].is_null());
                        let _=sqlx::query("INSERT OR IGNORE INTO speaker_jobs(meeting_id,status) VALUES(?,?)").bind(&id).bind(if complete {"complete"} else {"queued"}).execute(pool).await;
                    }
                }
                initialized=true;
            }
            if crate::is_recording().await {continue}
            let row=sqlx::query_as::<_,(String,Option<i64>)>("SELECT meeting_id,participant_count FROM speaker_jobs WHERE status='queued' ORDER BY rowid LIMIT 1")
                .fetch_optional(pool).await;
            let Ok(Some((id,count)))=row else {continue};
            let _=sqlx::query("UPDATE speaker_jobs SET status='running',error=NULL WHERE meeting_id=?").bind(&id).execute(pool).await;
            let _=app.emit("speaker-analysis-updated", &id);
            let result=speaker_action(app.clone(),app.state::<AppState>(),id.clone(),"analyze".into(),None,None,None,
                count.filter(|n|(1..=20).contains(n)).map(|n|n as i32),Some(false),None,None,None).await;
            let (status,error)=match result {Ok(_)=>("complete",None),Err(e)=> if crate::is_recording().await {("queued",Some(e))} else {("failed",Some(e))}};
            let _=sqlx::query("UPDATE speaker_jobs SET status=?,error=? WHERE meeting_id=?").bind(status).bind(error).bind(&id).execute(pool).await;
            let _=app.emit("speaker-analysis-updated", &id);
        }
    });
}

/// Copy labels made while recording to the final saved meeting before analysis starts.
pub async fn carry_live<R:tauri::Runtime>(app:&tauri::AppHandle<R>,live_id:&str,meeting_id:&str)->Result<(),String> {
    let _guard=LIVE_LABEL_LOCK.lock().await;
    use sha2::{Digest,Sha256};
    use sqlx::{Connection,sqlite::SqliteConnectOptions};
    let path=app.path().app_data_dir().map_err(|e|e.to_string())?.join("speaker-recognition/voices.sqlite");
    if !path.is_file(){return Ok(())}
    let mut db=sqlx::SqliteConnection::connect_with(&SqliteConnectOptions::new().filename(path)).await.map_err(|e|e.to_string())?;
    let source=format!("{:x}",Sha256::digest(live_id.as_bytes()));
    let target=format!("{:x}",Sha256::digest(meeting_id.as_bytes()));
    sqlx::query("INSERT OR IGNORE INTO meetings(id,data) SELECT ?,data FROM meetings WHERE id=?").bind(target).bind(source).execute(&mut db).await.map_err(|e|e.to_string())?;
    Ok(())
}
