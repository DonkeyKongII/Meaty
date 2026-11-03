const HOST = 'ai.meetily.meeting_autostart';
// Serialize mutations so a delayed joined reply cannot overwrite an ended session.
let queue = Promise.resolve();
function enqueue(action) {
  const result = queue.then(action);
  queue = result.catch(() => {});
  return result;
}
async function deliver(message, tabId) {
  const key = `accepted:${tabId}:${message.session}`;
  if (message.event === 'joined') {
    const {enabled = true} = await chrome.storage.local.get('enabled');
    if (!enabled) return {accepted:false, disabled:true};
    if ((await chrome.storage.session.get(key))[key]) {
      if (!Number.isInteger(message.participant_count) || message.participant_count < 1 || message.participant_count > 100) return {accepted:true};
      message = {...message, event:'participants'};
    }
  }
  try {
    const result = await chrome.runtime.sendNativeMessage(HOST, {...message, session:`${tabId}:${message.session}`});
    if (result.accepted) {
      if (message.event === 'joined') await chrome.storage.session.set({[key]:true});
      else if (message.event === 'ended') await chrome.storage.session.remove([key]);
    }
    if (message.event !== 'participants') await chrome.storage.local.set({lastStatus:result.accepted
      ? (message.event === 'joined' ? 'Meeting sent to Meetily. Check its recording indicator.' : 'Meeting ended. Meetily will stop after the reconnect grace period.')
      : 'Meetily did not accept the request.'});
    return result;
  } catch (error) {
    await chrome.storage.local.set({lastStatus:error.message});
    return {accepted:false, error:error.message};
  }
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (!sender.tab || !sender.url?.startsWith('https://meet.google.com/') ||
      !['joined','ended'].includes(message.event) || message.provider !== 'google-meet' ||
      typeof message.session !== 'string' || !message.session.length || message.session.length > 100) return;
  enqueue(() => deliver(message, sender.tab.id)).then(reply, error => reply({accepted:false,error:error.message}));
  return true;
});
chrome.tabs.onRemoved.addListener(tabId => enqueue(async () => {
  const entries = await chrome.storage.session.get(null);
  for (const key of Object.keys(entries).filter(key => key.startsWith(`accepted:${tabId}:`))) {
    await deliver({event:'ended',provider:'google-meet',session:key.slice(`accepted:${tabId}:`.length)},tabId);
  }
}));
