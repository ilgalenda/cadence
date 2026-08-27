const DEFAULT_BACKEND = 'http://localhost:8000';

const dot = document.getElementById('dot');
const statusText = document.getElementById('status-text');
const lineCount = document.getElementById('line-count');
const btnStart = document.getElementById('btn-start');
const btnEnd = document.getElementById('btn-end');
const resultLink = document.getElementById('result-link');
const resultAnchor = document.getElementById('result-anchor');
const errorMsg = document.getElementById('error-msg');
const backendInput = document.getElementById('backend-url');

function setStatus(state, count) {
  dot.className = 'dot' + (state === 'recording' ? ' recording' : state === 'done' ? ' done' : '');
  if (state === 'recording') {
    statusText.textContent = 'Recording';
    lineCount.textContent = count ? `${count} lines` : '';
    btnStart.disabled = true;
    btnEnd.disabled = false;
  } else if (state === 'submitting') {
    statusText.textContent = 'Submitting…';
    btnStart.disabled = true;
    btnEnd.disabled = true;
  } else if (state === 'done') {
    statusText.textContent = 'Done';
    lineCount.textContent = '';
    btnStart.disabled = false;
    btnEnd.disabled = true;
  } else {
    statusText.textContent = 'Idle';
    lineCount.textContent = '';
    btnStart.disabled = false;
    btnEnd.disabled = true;
  }
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.style.display = 'block';
}

function clearError() {
  errorMsg.style.display = 'none';
}

function getBackend() {
  return (backendInput.value || '').trim().replace(/\/$/, '') || DEFAULT_BACKEND;
}

// Load saved backend URL
chrome.storage.local.get(['backendUrl'], (res) => {
  backendInput.value = res.backendUrl || DEFAULT_BACKEND;
});

backendInput.addEventListener('change', () => {
  chrome.storage.local.set({ backendUrl: backendInput.value });
});

// Restore state from storage on popup open
chrome.storage.local.get(['isRecording', 'lineCount'], (res) => {
  if (res.isRecording) {
    setStatus('recording', res.lineCount || 0);
  }
});

// Listen for status updates from content script
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'status') {
    setStatus('recording', msg.lineCount);
    chrome.storage.local.set({ lineCount: msg.lineCount });
  }
});

async function getMeetTab() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tab = tabs.find(t => t.url && t.url.includes('meet.google.com'));
      resolve(tab || null);
    });
  });
}

btnStart.addEventListener('click', async () => {
  clearError();
  const tab = await getMeetTab();
  if (!tab) {
    showError('Open a Google Meet tab first.');
    return;
  }
  chrome.tabs.sendMessage(tab.id, { action: 'start' }, (res) => {
    if (chrome.runtime.lastError || !res || !res.ok) {
      showError('Could not start recording. Is a Google Meet open?');
      return;
    }
    chrome.storage.local.set({ isRecording: true, sessionId: res.sessionId, lineCount: 0 });
    setStatus('recording', 0);
  });
});

btnEnd.addEventListener('click', async () => {
  clearError();
  const tab = await getMeetTab();
  if (!tab) {
    showError('Google Meet tab not found.');
    return;
  }

  setStatus('submitting');

  chrome.tabs.sendMessage(tab.id, { action: 'stop' }, async (res) => {
    if (chrome.runtime.lastError || !res || !res.ok) {
      showError('Failed to collect transcript from the page.');
      setStatus('recording', 0);
      return;
    }

    const { lines, sessionId } = res;
    if (!lines || lines.length === 0) {
      showError('No captions captured. Make sure captions are enabled in Meet.');
      setStatus('idle');
      return;
    }

    const transcript = lines.join('\n');
    const title = `Google Meet — ${new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}`;
    const backend = getBackend();

    // Open the SamOS analyse page, passing transcript via hash so no auth is needed for the extension
    const payload = encodeURIComponent(JSON.stringify({ transcript, title, session_id: sessionId }));
    const analyseUrl = `${backend}/agents/calls/analyze#meet=${payload}`;

    chrome.tabs.create({ url: analyseUrl });
    chrome.storage.local.set({ isRecording: false, lastSessionId: sessionId });

    resultAnchor.href = analyseUrl;
    resultLink.style.display = 'block';
    setStatus('done');
  });
});
