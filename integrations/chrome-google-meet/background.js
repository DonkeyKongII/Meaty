const HOST = 'ai.meetily.meeting_autostart';
const MEETING_URL = /^https:\/\/meet\.google\.com\/(?:meet\/)?[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?]|$)/;
// Serialize mutations so a delayed joined reply cannot overwrite an ended session.
let queue = Promise.resolve();
function enqueue(action) {
  const result = queue.then(action);
  queue = result.catch(() => {});
  return result;
}
// Persistent native-messaging port: one native-host process for the whole
// browser session instead of a fresh Python interpreter per 2s poll. Responses
// arrive in request order (the host handles one message at a time).
let port = null;
const pending = [];
function ensurePort() {
  if (port) return port;
  const p = chrome.runtime.connectNative(HOST);
  port = p;
  p.onMessage.addListener(response => {
    const resolve = pending.shift();
    if (resolve) resolve(response);
  });
  p.onDisconnect.addListener(() => {
    if (port !== p) return;  // a replacement port already took over
    port = null;
    const error = chrome.runtime.lastError?.message || 'Native host disconnected';
    while (pending.length) pending.shift()({accepted:false, error});
  });
  return p;
}
function sendNative(message) {
  return new Promise(resolve => {
    let p;
    try { p = ensurePort(); }
    catch (error) { resolve({accepted:false, error:error.message}); return; }
    pending.push(resolve);
    try { p.postMessage(message); }
    catch (error) {
      // A synchronous send failure must not leave a waiter in the FIFO: the
      // next response would be consumed by an already-resolved promise.
      const index = pending.indexOf(resolve);
      if (index >= 0) pending.splice(index, 1);
      if (port === p) port = null;
      resolve({accepted:false, error:error.message});
    }
  });
}
async function deliver(message, tabId) {
  const key = `accepted:${tabId}:${message.session}`;
  if (message.event === 'joined') {
    const {enabled = true} = await chrome.storage.local.get('enabled');
    if (!enabled) return {accepted:false, disabled:true};
    if ((await chrome.storage.session.get(key))[key]) {
      if (Number.isInteger(message.participant_count) && message.participant_count >= 1 && message.participant_count <= 100) {
        message = {...message, event:'participants'};
      } else {
        // No reliable participant count: still forward a bare heartbeat. The
        // app treats 60s of silence as a dead tab and would stop the
        // recording of a meeting that is very much alive.
        message = {event:'participants', provider:message.provider, session:message.session};
      }
    }
  }
  const result = await sendNative({...message, session:`${tabId}:${message.session}`});
  if (result.accepted) {
    if (message.event === 'joined') await chrome.storage.session.set({[key]:true});
    else if (message.event === 'ended') await chrome.storage.session.remove([key]);
  } else {
    // The app could not be reached or rejected the event. Drop the accepted
    // marker so the next poll is a fresh "joined" that can (re)launch the app
    // instead of a "participants" heartbeat — otherwise auto-start is starved
    // for the rest of the call after an app restart mid-meeting.
    await chrome.storage.session.remove([key]);
  }
  if (message.event !== 'participants') await chrome.storage.local.set({lastStatus:result.accepted
    ? (message.event === 'joined' ? 'Meeting sent to Meetily. Check its recording indicator.' : 'Meeting ended. Meetily will stop after the reconnect grace period.')
    : (result.error || 'Meetily did not accept the request.')});
  return result;
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (!sender.tab || !sender.url?.startsWith('https://meet.google.com/') ||
      !['joined','ended'].includes(message.event) || message.provider !== 'google-meet' ||
      typeof message.session !== 'string' || !message.session.length || message.session.length > 100) return;
  enqueue(() => deliver(message, sender.tab.id)).then(reply, error => reply({accepted:false,error:error.message}));
  return true;
});
async function endSessionsForTab(tabId) {
  const entries = await chrome.storage.session.get(null);
  for (const key of Object.keys(entries).filter(key => key.startsWith(`accepted:${tabId}:`))) {
    await deliver({event:'ended',provider:'google-meet',session:key.slice(`accepted:${tabId}:`.length)},tabId);
  }
}
chrome.tabs.onRemoved.addListener(tabId => enqueue(() => endSessionsForTab(tabId)));
// Navigating the Meet tab somewhere else (back button, typed URL) never fires
// content.js' leave-button detection, so watch for the URL leaving the meeting.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!changeInfo.url || MEETING_URL.test(changeInfo.url)) return;
  return enqueue(() => endSessionsForTab(tabId));
});
