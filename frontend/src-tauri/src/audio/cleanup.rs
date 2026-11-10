//! Durable post-meeting transcription cleanup. Only newly saved recordings are queued.
use crate::state::AppState;
use serde_json::{json, Value};
use sqlx::SqlitePool;
use tauri::{Emitter, Manager};

pub(crate) static AUDIO_JOB_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

/// Let an active segment finish, then yield batch engines to the next meeting.
pub(crate) async fn before_recording() -> tokio::sync::MutexGuard<'static, ()> {
    let guard = loop {
        super::retranscription::cancel_retranscription();
        tokio::select! {
            guard = AUDIO_JOB_LOCK.lock() => break guard,
            _ = tokio::time::sleep(std::time::Duration::from_millis(100)) => {},
        }
    };
    while super::retranscription::is_retranscription_in_progress() {
        super::retranscription::cancel_retranscription();
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    guard
}

pub(crate) async fn schema(pool: &SqlitePool) -> Result<(), String> {
    sqlx::query("CREATE TABLE IF NOT EXISTS transcript_cleanup_jobs (meeting_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'queued', provider TEXT NOT NULL, model TEXT NOT NULL, language TEXT, retain_audio INTEGER NOT NULL, error TEXT, metrics TEXT, audio_deleted INTEGER NOT NULL DEFAULT 0)")
        .execute(pool).await.map_err(|e|e.to_string())?;
    Ok(())
}

pub(crate) async fn enqueue<R: tauri::Runtime>(app: &tauri::AppHandle<R>, id: &str) -> Result<(),String> {
    let state=app.state::<AppState>(); let pool=state.db_manager.pool(); schema(pool).await?;
    let config=crate::api::api::api_get_transcript_config(app.clone(),app.state(),None).await?;
    let (provider,model)=config.map(|c|(c.provider,c.model)).unwrap_or_else(||("parakeet".into(),crate::config::DEFAULT_PARAKEET_MODEL.into()));
    let prefs=super::recording_preferences::load_recording_preferences(app).await.map_err(|e|e.to_string())?;
    sqlx::query("INSERT OR IGNORE INTO transcript_cleanup_jobs(meeting_id,provider,model,language,retain_audio) VALUES(?,?,?,?,?)")
        .bind(id).bind(provider).bind(model).bind(crate::get_language_preference_internal()).bind(prefs.auto_save)
        .execute(pool).await.map_err(|e|e.to_string())?;
    Ok(())
}

pub(crate) async fn status(pool: &SqlitePool,id: &str) -> Result<(String,Option<String>),String> {
    schema(pool).await?;
    Ok(sqlx::query_as("SELECT status,error FROM transcript_cleanup_jobs WHERE meeting_id=?")
        .bind(id).fetch_optional(pool).await.map_err(|e|e.to_string())?.unwrap_or(("not_queued".into(),None)))
}

/// Failure is a hard gate: never silently summarize the provisional transcript.
pub(crate) async fn ready(pool: &SqlitePool,id: &str) -> Result<bool,String> {
    let (state,error)=status(pool,id).await?;
    match state.as_str() {
        "complete"|"not_queued" => Ok(true),
        "queued"|"running" => Ok(false),
        _ => Err(format!("Transcript cleanup needs attention: {}",error.unwrap_or(state))),
    }
}

#[tauri::command]
pub async fn retry_transcript_cleanup(app: tauri::AppHandle,meeting_id: String) -> Result<(),String> {
    let state=app.state::<AppState>();let pool=state.db_manager.pool();schema(pool).await?;
    sqlx::query("UPDATE transcript_cleanup_jobs SET status='queued',error=NULL WHERE meeting_id=? AND status='failed'")
        .bind(&meeting_id).execute(pool).await.map_err(|e|e.to_string())?;
    sqlx::query("UPDATE meeting_pipeline SET status='waiting',error=NULL,queued_at=unixepoch() WHERE meeting_id=? AND status='failed'")
        .bind(&meeting_id).execute(pool).await.map_err(|e|e.to_string())?;
    let _=app.emit("meeting-pipeline-updated",&meeting_id);
    Ok(())
}

pub(crate) async fn recover(pool: &SqlitePool) -> Result<(),String> {
    schema(pool).await?;
    sqlx::query("UPDATE transcript_cleanup_jobs SET status='queued' WHERE status='running'")
        .execute(pool).await.map_err(|e|e.to_string())?;
    Ok(())
}

/// Run at most one job per tick. No engines run alongside a live recording.
pub(crate) async fn process_next(app: &tauri::AppHandle) -> Result<(),String> {
    let Ok(_guard)=AUDIO_JOB_LOCK.try_lock() else{return Ok(())};
    if crate::is_recording().await || super::retranscription::is_retranscription_in_progress(){return Ok(())}
    let state=app.state::<AppState>();let pool=state.db_manager.pool();
    let row=sqlx::query_as::<_,(String,String,String,Option<String>)>("SELECT meeting_id,provider,model,language FROM transcript_cleanup_jobs WHERE status='queued' ORDER BY rowid LIMIT 1")
        .fetch_optional(pool).await.map_err(|e|e.to_string())?;
    let Some((id,provider,model,language))=row else{return Ok(())};
    sqlx::query("UPDATE transcript_cleanup_jobs SET status='running',error=NULL WHERE meeting_id=?")
        .bind(&id).execute(pool).await.map_err(|e|e.to_string())?;
    let _=app.emit("meeting-pipeline-updated",&id);
    let outcome=async {
        let folder=sqlx::query_scalar::<_,Option<String>>("SELECT folder_path FROM meetings WHERE id=?")
            .bind(&id).fetch_optional(pool).await.map_err(|e|e.to_string())?.flatten().ok_or("No saved recording folder. The live transcript was kept.")?;
        let before=super::retranscription::snapshot(pool,&id).await.map_err(|e|e.to_string())?;
        let result=super::retranscription::cleanup_recording(app.clone(),id.clone(),folder.clone(),language,model,provider).await.map_err(|e|e.to_string())?;
        let after=super::retranscription::snapshot(pool,&id).await.map_err(|e|e.to_string())?;
        // Diagnostic data supports future measured tuning; it is not a training label.
        let metrics=json!({"live_segments":before.len(),"final_segments":after.len(),"live_words":before.iter().map(|s|s.1.split_whitespace().count()).sum::<usize>(),"final_words":after.iter().map(|s|s.1.split_whitespace().count()).sum::<usize>(),"recording_seconds":result.duration_seconds,"method":"full_audio_silence_aware_second_pass"});
        sqlx::query("UPDATE transcript_cleanup_jobs SET metrics=? WHERE meeting_id=?")
            .bind(metrics.to_string()).bind(&id).execute(pool).await.map_err(|e|e.to_string())?;
        Ok::<(),String>(())
    }.await;
    let (status,error)=match outcome {
        Ok(()) => ("complete",None),
        Err(e) if e.contains("cancelled") => ("queued",Some(e)),
        Err(e) => ("failed",Some(e)),
    };
    sqlx::query("UPDATE transcript_cleanup_jobs SET status=?,error=? WHERE meeting_id=?")
        .bind(status).bind(error).bind(&id).execute(pool).await.map_err(|e|e.to_string())?;
    let _=app.emit("meeting-pipeline-updated",&id);
    Ok(())
}

/// Retention is decided when the meeting is queued, never retroactively for old audio.
/// Speaker analysis also needs the recording, so a failure there preserves it for retry.
pub(crate) async fn delete_finished_audio(pool: &SqlitePool) -> Result<(),String> {
    let rows=sqlx::query_as::<_,(String,String)>("SELECT j.meeting_id,m.folder_path FROM transcript_cleanup_jobs j JOIN meetings m ON m.id=j.meeting_id JOIN speaker_jobs s ON s.meeting_id=j.meeting_id WHERE j.status='complete' AND j.retain_audio=0 AND j.audio_deleted=0 AND s.status='complete' AND m.folder_path IS NOT NULL")
        .fetch_all(pool).await.map_err(|e|e.to_string())?;
    for (id,folder) in rows {
        let folder=std::path::Path::new(&folder);
        // Only remove the canonical file owned by our live recording path.
        let path=folder.join("audio.mp4");
        if !folder.join("transcripts.json").is_file(){continue}
        match std::fs::remove_file(path) {
            Ok(())=>{},
            Err(e) if e.kind()==std::io::ErrorKind::NotFound=>{},
            Err(e)=>{log::warn!("Could not delete processed meeting audio: {e}");continue},
        }
        let meta=folder.join("metadata.json");
        if let Ok(bytes)=std::fs::read(&meta) {
            if let Ok(mut data)=serde_json::from_slice::<Value>(&bytes) {
                data["audio_file"]=json!("");data["audio_deleted_after_cleanup"]=json!(true);
                if let Ok(bytes)=serde_json::to_vec_pretty(&data){let _=std::fs::write(meta,bytes);}
            }
        }
        sqlx::query("UPDATE transcript_cleanup_jobs SET audio_deleted=1 WHERE meeting_id=?")
            .bind(id).execute(pool).await.map_err(|e|e.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    async fn fixture()->SqlitePool {
        let pool=sqlx::sqlite::SqlitePoolOptions::new().max_connections(1).connect("sqlite::memory:").await.unwrap();
        schema(&pool).await.unwrap();
        sqlx::query("INSERT INTO transcript_cleanup_jobs(meeting_id,provider,model,retain_audio) VALUES('m','parakeet','test',1)").execute(&pool).await.unwrap();pool
    }
    #[tokio::test] async fn cleanup_is_a_hard_summary_gate() {
        let pool=fixture().await;
        assert!(!ready(&pool,"m").await.unwrap());
        sqlx::query("UPDATE transcript_cleanup_jobs SET status='running'").execute(&pool).await.unwrap();
        assert!(!ready(&pool,"m").await.unwrap());
        sqlx::query("UPDATE transcript_cleanup_jobs SET status='failed',error='missing audio'").execute(&pool).await.unwrap();
        assert!(ready(&pool,"m").await.unwrap_err().contains("missing audio"));
        sqlx::query("UPDATE transcript_cleanup_jobs SET status='complete'").execute(&pool).await.unwrap();
        assert!(ready(&pool,"m").await.unwrap());
        assert!(ready(&pool,"older-meeting").await.unwrap());
    }
    #[tokio::test] async fn interrupted_job_resumes_without_touching_failed_or_complete_jobs() {
        let pool=fixture().await;
        sqlx::query("UPDATE transcript_cleanup_jobs SET status='running'").execute(&pool).await.unwrap();
        recover(&pool).await.unwrap();assert_eq!(status(&pool,"m").await.unwrap().0,"queued");
        sqlx::query("UPDATE transcript_cleanup_jobs SET status='failed'").execute(&pool).await.unwrap();
        recover(&pool).await.unwrap();assert_eq!(status(&pool,"m").await.unwrap().0,"failed");
    }
    #[tokio::test] async fn audio_deletion_requires_success_and_respects_retention() {
        let pool=fixture().await;
        sqlx::query("CREATE TABLE meetings(id TEXT,folder_path TEXT)").execute(&pool).await.unwrap();
        sqlx::query("CREATE TABLE speaker_jobs(meeting_id TEXT,status TEXT)").execute(&pool).await.unwrap();
        let dir=std::env::temp_dir().join(format!("meaty-cleanup-test-{}",uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("audio.mp4"),b"audio fixture").unwrap();
        std::fs::write(dir.join("transcripts.json"),b"{}").unwrap();
        std::fs::write(dir.join("unrelated.mp4"),b"keep").unwrap();
        sqlx::query("INSERT INTO meetings VALUES('m',?)").bind(dir.to_str().unwrap()).execute(&pool).await.unwrap();
        sqlx::query("INSERT INTO speaker_jobs VALUES('m','complete')").execute(&pool).await.unwrap();
        sqlx::query("UPDATE transcript_cleanup_jobs SET retain_audio=0,status='failed'").execute(&pool).await.unwrap();
        delete_finished_audio(&pool).await.unwrap();assert!(dir.join("audio.mp4").exists());
        sqlx::query("UPDATE transcript_cleanup_jobs SET status='complete',retain_audio=1").execute(&pool).await.unwrap();
        delete_finished_audio(&pool).await.unwrap();assert!(dir.join("audio.mp4").exists());
        sqlx::query("UPDATE transcript_cleanup_jobs SET retain_audio=0").execute(&pool).await.unwrap();
        sqlx::query("UPDATE speaker_jobs SET status='failed'").execute(&pool).await.unwrap();
        delete_finished_audio(&pool).await.unwrap();assert!(dir.join("audio.mp4").exists());
        sqlx::query("UPDATE speaker_jobs SET status='complete'").execute(&pool).await.unwrap();
        delete_finished_audio(&pool).await.unwrap();assert!(!dir.join("audio.mp4").exists());
        assert!(dir.join("unrelated.mp4").exists());
        assert_eq!(sqlx::query_scalar::<_,i64>("SELECT audio_deleted FROM transcript_cleanup_jobs").fetch_one(&pool).await.unwrap(),1);
        std::fs::remove_dir_all(dir).unwrap();
    }

}
