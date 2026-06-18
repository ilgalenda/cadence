// IvanOS Meet Capture — content script
// Observes Google Meet's caption DOM and accumulates a timestamped transcript.
//
// MAINTAINABILITY NOTE:
// Google Meet uses obfuscated class names that change with each deployment.
// If captions stop being captured after a Meet update:
//   1. Open a meeting with captions enabled (CC button in the bottom bar)
//   2. Open DevTools → Elements, look for the element whose text updates as people speak
//   3. Add its selector to CAPTION_SELECTORS or SPEAKER_SELECTORS below

const CAPTION_SELECTORS = [
  '[data-message-text]',
  '[jsname="tgaKEf"]',
  '[jsname="YSxPC"] span',
  '.a4cQT span',
];

const SPEAKER_SELECTORS = [
  '[data-sender-name]',
  '[jsname="r4nke"]',
  '.zs7s8d',
];

let lines = [];
let lastSpeaker = '';
let lastText = '';
let isRecording = false;
let sessionId = null;

function pad(n) {
  return String(n).padStart(2, '0');
}

function timestamp() {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function extractSpeaker(el) {
  // Walk up the DOM looking for a speaker label sibling or ancestor attribute
  let node = el;
  for (let i = 0; i < 8; i++) {
    if (!node) break;
    const name = node.getAttribute('data-sender-name');
    if (name) return name;
    for (const sel of SPEAKER_SELECTORS) {
      const found = node.querySelector(sel);
      if (found && found.textContent.trim()) return found.textContent.trim();
    }
    node = node.parentElement;
  }
  return '';
}

function onCaption(el) {
  if (!isRecording) return;
  const text = el.textContent.trim();
  if (!text) return;

  const speaker = extractSpeaker(el) || 'Unknown';
  const ts = timestamp();

  if (text === lastText && speaker === lastSpeaker) return;

  const line = `[${ts}] ${speaker}: ${text}`;

  // Replace the last line when the same speaker is still talking (in-place caption update)
  if (speaker === lastSpeaker && lines.length > 0) {
    lines[lines.length - 1] = line;
  } else {
    lines.push(line);
  }

  lastSpeaker = speaker;
  lastText = text;

  // Notify popup if open
  chrome.runtime.sendMessage({ type: 'status', lineCount: lines.length }).catch(() => {});
}

function tryNode(node) {
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  for (const sel of CAPTION_SELECTORS) {
    if (node.matches && node.matches(sel)) {
      onCaption(node);
    }
    node.querySelectorAll(sel).forEach(onCaption);
  }
}

const observer = new MutationObserver((mutations) => {
  for (const m of mutations) {
    for (const node of m.addedNodes) tryNode(node);
    if (m.type === 'characterData' && m.target.parentElement) {
      tryNode(m.target.parentElement);
    }
  }
});

observer.observe(document.body, {
  childList: true,
  subtree: true,
  characterData: true,
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === 'start') {
    lines = [];
    lastSpeaker = '';
    lastText = '';
    sessionId = ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
      (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
    );
    isRecording = true;
    sendResponse({ ok: true, sessionId });
  } else if (msg.action === 'stop') {
    isRecording = false;
    sendResponse({ ok: true, lines, sessionId });
  } else if (msg.action === 'getState') {
    sendResponse({ isRecording, lineCount: lines.length, sessionId });
  }
  return true; // keep channel open for async sendResponse
});
