// Require a visible leave-call control: the pre-join camera/mic preview is insufficient.
(() => {
  const storageKey = `meetily:session:${location.pathname}`;
  let session = sessionStorage.getItem(storageKey);
  let absentSince = null;
  let running = false;
  // Send-on-change: only message the bridge when the participant count changes,
  // plus a heartbeat every 15s so the app can tell a stable meeting from a dead
  // tab (it stops the recording after ~60s of silence).
  let lastSignature = null;
  let lastSentAt = 0;
  const HEARTBEAT_MS = 15000;
  function joined() {
    if (!/^\/(?:meet\/)?[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?]|$)/.test(location.pathname)) return false;
    return [...document.querySelectorAll('button, [role="button"]')].some(el => {
      const visible = el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
      const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('data-tooltip') || ''}`;
      const hangupIcon = [...el.querySelectorAll('i, span')].some(icon => icon.textContent.trim() === 'call_end');
      return visible && (/\b(leave call|leave the call|leave meeting|hang up)\b/i.test(label) || hangupIcon);
    });
  }
  // Only explicit participant-count controls; never infer attendance from tile count.
  function participantCount() {
    for (const el of document.querySelectorAll('[aria-label], [data-tooltip], [data-participant-count], [role="button"][aria-labelledby], button[aria-labelledby]')) {
      if (!el.getClientRects().length || getComputedStyle(el).visibility === 'hidden') continue;
      const explicit = el.getAttribute('data-participant-count');
      const labelledBy = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>id ? document.getElementById(id)?.textContent || '' : '').join(' ');
      const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('data-tooltip') || ''} ${labelledBy}`;
      const match = label.match(/(?:participants?|people|in.call)[^\d]{0,20}(\d{1,3})\b/i)
        || label.match(/\b(\d{1,3})\s+(?:participants?|people)\b/i);
      const textCount = /(?:participants?|people|show everyone)/i.test(label) ? el.textContent?.trim().match(/(\d{1,3})\s*$/)?.[1] : null;
      const count = Number(explicit || match?.[1] || textCount);
      if (Number.isInteger(count) && count >= 1 && count <= 100) return count;
    }
    return null;
  }
  let lastRosterAt = 0;
  let metadata = {};
  const ROSTER_MS = 5 * 60 * 1000;
  function meetingMetadata() {
    // Read explicit Meet participant identities, including offscreen roster rows.
    // Do not turn arbitrary tile text, captions, or chat messages into people.
    const people = new Map();
    for (const el of document.querySelectorAll('[data-participant-id], [data-requested-participant-id]')) {
      const nameNode = el.querySelector?.('[data-self-name], [data-participant-name], [data-hovercard-id]');
      const name = (el.getAttribute('data-participant-name') || el.getAttribute('data-self-name') || nameNode?.getAttribute('data-self-name') || nameNode?.getAttribute('data-participant-name') || nameNode?.textContent || '').trim().replace(/\s*\(You\)\s*$/i, '').slice(0, 100);
      if (!name || /^(you|presentation|screen share)$/i.test(name)) continue;
      people.set(name.toLocaleLowerCase(), {name, attendance:'confirmed'});
      if (people.size >= 100) break;
    }
    const titleNode = document.querySelector?.('[data-meeting-title]');
    const rawTitle = titleNode?.getAttribute('data-meeting-title') || titleNode?.textContent || document.title || '';
    const title = rawTitle.replace(/^Meet\s*[-–—]\s*/i, '').replace(/\s*[-–—]\s*Google Meet$/i, '').trim();
    return {participants:[...people.values()], meet_title: /^(Google Meet|Meet|[a-z]{3}-[a-z]{4}-[a-z]{3})$/i.test(title)?'':title.slice(0,500), meet_url:`https://meet.google.com/${location.pathname.match(/[a-z]{3}-[a-z]{4}-[a-z]{3}/)?.[0]||''}`};
  }
  async function check() {
    if (running) return;
    if (!joined()) {
      absentSince ??= Date.now();
      if (session) {
        running = true;
        try {
          const result = await chrome.runtime.sendMessage({event:'ended', provider:'google-meet', session});
          // Force a fresh "joined" on rejoin so the app can cancel the stop
          // grace — send-on-change must never suppress it.
          lastSignature = null;
          lastRosterAt = 0;
          metadata = {};
          if (result?.accepted && Date.now() - absentSince > 5000) {
            session = null;
            sessionStorage.removeItem(storageKey);
          }
        } catch (error) { console.debug('Meetily end notification unavailable:', error.message); }
        finally { running = false; }
      }
      return;
    }
    absentSince = null;
    if (!session) {
      session = crypto.randomUUID();
      sessionStorage.setItem(storageKey, session);
    }
    running = true;
    try {
    const count = participantCount();
    if (!lastRosterAt || Date.now() - lastRosterAt >= (metadata.participants?.length&&(!count||metadata.participants.length>=count)?ROSTER_MS:15000)) {
      // Meet only mounts the full roster when People is open. Briefly open it
      // for the snapshot, restoring the user's previous panel afterwards.
      const peopleButton = [...document.querySelectorAll('button, [role="button"]')].find(el =>
        el.getClientRects().length && typeof el.click === 'function' &&
        /^(show everyone|people|participants)(?:\b|$)/i.test(el.getAttribute('aria-label') || '') &&
        el.getAttribute('aria-expanded') === 'false');
      if (peopleButton) {peopleButton.click();await new Promise(resolve=>setTimeout(resolve,750));}
      metadata = meetingMetadata();
      if (peopleButton?.getAttribute('aria-expanded') === 'true') peopleButton.click();
      lastRosterAt = Date.now();
    }
    const signature = `${session}:${count}`;
    if (signature === lastSignature && Date.now() - lastSentAt < HEARTBEAT_MS) return;
      const result = await chrome.runtime.sendMessage({event:'joined', provider:'google-meet', session, participant_count:count, ...metadata});
      if (!result?.accepted) return;
      lastSignature = signature;
      lastSentAt = Date.now();
    }
    catch (error) { console.debug('Meetily extension unavailable:', error.message); }
    finally { running = false; }
  }
  // Best-effort end notice when the page unloads (refresh, navigation, close);
  // tab close is also caught background-side via tabs.onRemoved.
  window.addEventListener('pagehide', () => {
    if (session) chrome.runtime.sendMessage({event:'ended', provider:'google-meet', session}).catch(() => {});
  });
  setInterval(check, 2000);
  check();
})();
