const HOST = 'ai.meetily.meeting_autostart';
let inFlight = false;
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (!sender.tab || !sender.url?.startsWith('https://meet.google.com/') ||
      message.event !== 'joined' || message.provider !== 'google-meet' ||
      typeof message.session !== 'string' || message.session.length > 128) return;
  (async () => {
    const {enabled = true} = await chrome.storage.local.get('enabled');
    if (!enabled) return {accepted:false, disabled:true};
    const key = `accepted:${sender.tab.id}:${message.session}`;
    if ((await chrome.storage.session.get(key))[key]) return {accepted:true};
    if (inFlight) return {accepted:false};
    inFlight = true;
    try {
      const result = await chrome.runtime.sendNativeMessage(HOST, message);
      if (result.accepted) await chrome.storage.session.set({[key]:true});
      await chrome.storage.local.set({lastStatus:result.accepted ? 'Meeting sent to Meetily. Check its recording indicator.' : 'Meetily did not accept the request.'});
      return result;
    } catch (error) {
      await chrome.storage.local.set({lastStatus:error.message});
      return {accepted:false, error:error.message};
    } finally { inFlight = false; }
  })().then(reply, error => reply({accepted:false, error:error.message}));
  return true;
});
chrome.tabs.onRemoved.addListener(async tabId => {
  const entries = await chrome.storage.session.get(null);
  const keys = Object.keys(entries).filter(key => key.startsWith(`accepted:${tabId}:`));
  if (keys.length) await chrome.storage.session.remove(keys);
});
