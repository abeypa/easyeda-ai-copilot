/**
 * Extension Service Worker
 * Proxies OpenRouter API calls to avoid CORS issues and centralises auth.
 * Also handles plugin injection and settings sync.
 */

const OPENROUTER_BASE = 'https://openrouter.ai/api/v1';

// ── Message handler ───────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case 'OPENROUTER_CHAT':
      handleChat(msg.payload).then(sendResponse).catch(e => sendResponse({ error: e.message }));
      return true; // keep channel open for async

    case 'OPENROUTER_MODELS':
      handleGetModels(msg.payload).then(sendResponse).catch(e => sendResponse({ error: e.message }));
      return true;

    case 'OPENROUTER_VALIDATE':
      handleValidateKey(msg.payload).then(sendResponse).catch(e => sendResponse({ error: e.message }));
      return true;

    case 'GET_SETTINGS':
      chrome.storage.sync.get(['apiKey', 'model', 'temperature', 'maxTokens'], sendResponse);
      return true;

    case 'SAVE_SETTINGS':
      chrome.storage.sync.set(msg.payload, () => sendResponse({ ok: true }));
      return true;

    case 'OPEN_PLUGIN':
      openPlugin(sender.tab?.id);
      sendResponse({ ok: true });
      return false;
  }
});

// ── OpenRouter handlers ───────────────────────────────────────────────────────
async function handleChat({ apiKey, model, messages, systemPrompt, temperature, maxTokens }) {
  const payload = {
    model,
    messages: systemPrompt ? [{ role: 'system', content: systemPrompt }, ...messages] : messages,
    stream: false,
    temperature: temperature ?? 0.7,
    max_tokens: maxTokens ?? 4096,
  };

  const res = await fetch(`${OPENROUTER_BASE}/chat/completions`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://easyeda.com',
      'X-Title': 'EasyEDA AI Copilot',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error?.message || `HTTP ${res.status}`);
  }

  const data = await res.json();
  return { content: data.choices?.[0]?.message?.content || '' };
}

async function handleGetModels({ apiKey }) {
  const res = await fetch(`${OPENROUTER_BASE}/models`, {
    headers: { 'Authorization': `Bearer ${apiKey}` },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return { models: data.data || [] };
}

async function handleValidateKey({ apiKey }) {
  const res = await fetch(`${OPENROUTER_BASE}/auth/key`, {
    headers: { 'Authorization': `Bearer ${apiKey}` },
  });
  if (!res.ok) return { valid: false };
  const data = await res.json();
  return { valid: true, data: data.data };
}

// ── Plugin injection ──────────────────────────────────────────────────────────
function openPlugin(tabId) {
  if (!tabId) return;
  // Inject a floating sidebar if not already present
  chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      if (document.getElementById('easyeda-ai-copilot-sidebar')) return;
      const sidebar = document.createElement('iframe');
      sidebar.id = 'easyeda-ai-copilot-sidebar';
      sidebar.src = chrome.runtime.getURL('plugin/index.html');
      Object.assign(sidebar.style, {
        position: 'fixed',
        top: '60px',
        right: '0',
        width: '400px',
        height: 'calc(100vh - 60px)',
        border: 'none',
        borderLeft: '1px solid #373a40',
        zIndex: '999999',
        boxShadow: '-4px 0 20px rgba(0,0,0,.5)',
        background: '#1a1b1e',
        transition: 'transform .3s ease',
      });
      document.body.appendChild(sidebar);
    },
  }).catch(console.error);
}

// ── Extension install handler ─────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === 'install') {
    chrome.tabs.create({ url: 'extension/popup/popup.html' });
  }
});
