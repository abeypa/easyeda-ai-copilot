/**
 * Extension popup script — settings management and quick launch.
 */

const $ = id => document.getElementById(id);

let saveTimer = null;

document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
  setupListeners();
  checkApiKey(false);
});

// ── Load / Save ───────────────────────────────────────────────────────────────
async function loadSettings() {
  const stored = await chrome.storage.sync.get(['apiKey', 'model']);
  if (stored.apiKey) $('apiKey').value = stored.apiKey;
  if (stored.model) $('modelSelect').value = stored.model;
}

async function saveSettings() {
  const apiKey = $('apiKey').value.trim();
  const model  = $('modelSelect').value;

  await chrome.storage.sync.set({ apiKey, model });

  $('saveBtn').textContent = '✓ Saved';
  setTimeout(() => { $('saveBtn').textContent = 'Save Settings'; }, 1800);

  if (apiKey) await checkApiKey(true);
}

// ── API Key validation ────────────────────────────────────────────────────────
async function checkApiKey(showToast) {
  const key = $('apiKey').value.trim();
  const dot = $('statusDot');
  const status = $('keyStatus');

  if (!key) {
    dot.className = 'status-dot';
    status.className = 'key-status';
    status.textContent = '';
    return;
  }

  status.className = 'key-status checking';
  status.textContent = 'Validating…';

  try {
    const res = await fetch('https://openrouter.ai/api/v1/auth/key', {
      headers: { 'Authorization': `Bearer ${key}` },
    });

    if (res.ok) {
      const data = await res.json();
      dot.className = 'status-dot connected';
      status.className = 'key-status ok';
      const label = data.data?.label || 'Valid';
      const usage = data.data?.usage != null
        ? ` · $${data.data.usage.toFixed(3)} used`
        : '';
      status.textContent = `✓ ${label}${usage}`;
    } else {
      dot.className = 'status-dot error';
      status.className = 'key-status error';
      status.textContent = `✗ Invalid key (${res.status})`;
    }
  } catch (_) {
    dot.className = 'status-dot error';
    status.className = 'key-status error';
    status.textContent = '✗ Could not reach OpenRouter';
  }
}

// ── Event listeners ───────────────────────────────────────────────────────────
function setupListeners() {
  $('saveBtn').addEventListener('click', saveSettings);

  $('toggleKey').addEventListener('click', () => {
    const input = $('apiKey');
    input.type = input.type === 'password' ? 'text' : 'password';
    $('toggleKey').textContent = input.type === 'password' ? '👁' : '🙈';
  });

  // Debounce key validation on input
  $('apiKey').addEventListener('input', () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => checkApiKey(false), 800);
  });

  // Quick launch buttons
  $('openEasyEDA').addEventListener('click', () =>
    chrome.tabs.create({ url: 'https://easyeda.com/editor' }));

  $('openLCSC').addEventListener('click', () =>
    chrome.tabs.create({ url: 'https://www.lcsc.com/' }));

  $('openJLCPCB').addEventListener('click', () =>
    chrome.tabs.create({ url: 'https://jlcpcb.com/parts' }));

  $('openDocs').addEventListener('click', () =>
    chrome.tabs.create({ url: 'https://github.com/abeypa/easyeda-ai-copilot#readme' }));
}
