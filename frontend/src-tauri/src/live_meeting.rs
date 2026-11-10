use serde_json::{json, Value};
use std::{collections::HashMap, path::PathBuf, sync::{LazyLock, Mutex}, time::{Duration, Instant}};
use tauri::Manager;
#[derive(Default)]
struct Live { sessions:HashMap<String,(Value,Instant)>, data:Value, path:Option<PathBuf> }
static LIVE:LazyLock<Mutex<Live>>=LazyLock::new(Default::default);
fn merge(data:&mut Value, message:&Value) {
    for field in ["meet_title","meet_url"] {
        if data[field].as_str().unwrap_or("").is_empty() {
            if let Some(value)=message[field].as_str().filter(|v|!v.is_empty() && v.len()<=2000) {data[field]=json!(value);}
        }
    }
    let mut people=data["participants"].as_array().cloned().unwrap_or_default();
    for p in message["participants"].as_array().into_iter().flatten().take(100) {
        let Some(name)=p["name"].as_str().map(str::trim).filter(|n|!n.is_empty()&&n.chars().count()<=100) else {continue};
        if people.len()<300 && !people.iter().any(|v|v["name"].as_str().unwrap_or("").to_lowercase()==name.to_lowercase()) {
            people.push(json!({"name":name,"email":"","attendance":"confirmed"}));
        }
    }
    data["participants"]=json!(people);
}
fn persist(live:&Live) {
    if let Some(path)=&live.path {
        let temp=path.with_extension("tmp");
        if let Ok(bytes)=serde_json::to_vec(&live.data) {
            if std::fs::write(&temp,bytes).is_ok() {
                #[cfg(unix)] {use std::os::unix::fs::PermissionsExt;let _=std::fs::set_permissions(&temp,std::fs::Permissions::from_mode(0o600));}
                let _=std::fs::rename(temp,path);
            }
        }
    }
}
pub fn begin<R:tauri::Runtime>(app:&tauri::AppHandle<R>) {
    let mut live=LIVE.lock().unwrap_or_else(|e|e.into_inner());
    live.path=app.path().app_data_dir().ok().map(|p|p.join("live-meeting.json"));
    live.data=json!({"live_id":format!("live-{}",uuid::Uuid::new_v4()),"participants":[]});
    let recent=live.sessions.values().filter(|(_,t)|t.elapsed()<Duration::from_secs(60)).map(|(v,_)|v.clone()).collect::<Vec<_>>();
    for message in recent {merge(&mut live.data,&message);}
    persist(&live);
}
pub fn observe(message:&Value) {
    let mut live=LIVE.lock().unwrap_or_else(|e|e.into_inner());
    let session=message["session"].as_str().unwrap_or("").to_owned();
    if message["event"]=="ended" {live.sessions.remove(&session);return;}
    live.sessions.retain(|_,(_,t)|t.elapsed()<Duration::from_secs(60));
    live.sessions.insert(session,(message.clone(),Instant::now()));
    if !live.data.is_null() {let before=live.data.clone();merge(&mut live.data,message);if before!=live.data {persist(&live);}}
}
pub fn snapshot<R:tauri::Runtime>(app:&tauri::AppHandle<R>)->Value {
    let mut live=LIVE.lock().unwrap_or_else(|e|e.into_inner());
    if live.data.is_null() {
        live.path=app.path().app_data_dir().ok().map(|p|p.join("live-meeting.json"));
        live.data=live.path.as_ref().and_then(|p|std::fs::read(p).ok()).and_then(|b|serde_json::from_slice(&b).ok()).unwrap_or_else(||json!({}));
    }
    live.data.clone()
}
pub fn take_for_save<R:tauri::Runtime>(app:&tauri::AppHandle<R>)->Value {
    let _=snapshot(app);
    let mut live=LIVE.lock().unwrap_or_else(|e|e.into_inner());
    if live.data["saved"].as_bool()==Some(true) {return json!({});}
    let data=live.data.clone();live.data["saved"]=json!(true);persist(&live);data
}
#[cfg(test)] mod tests {
 use super::*;
 #[test] fn roster_is_additive_and_case_insensitive() {
  let mut data=json!({});
  merge(&mut data,&json!({"participants":[{"name":"Ian"},{"name":"Will"},{"name":"Vijay"}],"meet_title":"Design"}));
  merge(&mut data,&json!({"participants":[{"name":"ian"},{"name":"Vijay"},{"name":"Madhvendra"}]}));
  assert_eq!(data["participants"].as_array().unwrap().len(),4);assert_eq!(data["meet_title"],"Design");
 }
}
