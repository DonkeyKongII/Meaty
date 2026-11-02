// Require a visible leave-call control: the pre-join camera/mic preview is insufficient.
(() => {
  const storageKey = `meetily:session:${location.pathname}`;
  let session = sessionStorage.getItem(storageKey);
  let absentSince = null;
  let running = false;
  function joined() {
    if (!/^\/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?]|$)/.test(location.pathname)) return false;
    return [...document.querySelectorAll('button, [role="button"]')].some(el => {
      const visible = el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
      const label = `${el.getAttribute('aria-label') || ''} ${el.getAttribute('data-tooltip') || ''}`;
      const hangupIcon = [...el.querySelectorAll('i, span')].some(icon => icon.textContent.trim() === 'call_end');
      return visible && (/\b(leave call|leave the call|leave meeting|hang up)\b/i.test(label) || hangupIcon);
    });
  }
  async function check() {
    if (running) return;
    if (!joined()) {
      absentSince ??= Date.now();
      if (Date.now() - absentSince > 5000) {
        session = null;
        sessionStorage.removeItem(storageKey);
      }
      return;
    }
    absentSince = null;
    if (!session) {
      session = crypto.randomUUID();
      sessionStorage.setItem(storageKey, session);
    }
    running = true;
    try { await chrome.runtime.sendMessage({event:'joined', provider:'google-meet', session}); }
    catch (error) { console.debug('Meetily extension unavailable:', error.message); }
    finally { running = false; }
  }
  setInterval(check, 2000);
  check();
})();
