// Require a visible leave-call control: the pre-join camera/mic preview is insufficient.
(() => {
  const storageKey = `meetily:session:${location.pathname}`;
  let session = sessionStorage.getItem(storageKey);
  let absentSince = null;
  let running = false;
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
  async function check() {
    if (running) return;
    if (!joined()) {
      absentSince ??= Date.now();
      if (session) {
        running = true;
        try {
          const result = await chrome.runtime.sendMessage({event:'ended', provider:'google-meet', session});
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
    try { await chrome.runtime.sendMessage({event:'joined', provider:'google-meet', session, participant_count:participantCount()}); }
    catch (error) { console.debug('Meetily extension unavailable:', error.message); }
    finally { running = false; }
  }
  setInterval(check, 2000);
  check();
})();
