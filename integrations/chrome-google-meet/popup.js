(async () => {
 const {enabled = true, lastStatus = 'Waiting for a Google Meet call.'} = await chrome.storage.local.get(['enabled','lastStatus']);
 const toggle = document.getElementById('enabled');
 toggle.checked = enabled;
 document.getElementById('status').textContent = lastStatus;
 toggle.addEventListener('change', () => chrome.storage.local.set({enabled:toggle.checked}));
})();
