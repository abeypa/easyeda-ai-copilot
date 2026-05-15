/**
 * EasyEDA AI Copilot — Main Application
 * Orchestrates all modules: chat, generate, analyze, BOM, settings.
 */

// ── Application State ─────────────────────────────────────────────────────────
const AppState = {
  apiKey: '',
  model: 'anthropic/claude-sonnet-4-5',
  temperature: 0.7,
  maxTokens: 4096,
  includeSchematicCtx: true,
  streamResponses: true,
  lcscPreference: true,
  chatHistory: [],       // [{role, content}]
  schematic: null,       // {raw, parsed}
  isStreaming: false,
  lastBOM: '',
};

// ── Initialization ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  UI.initMarkdown();
  loadSettings();
  setupEventListeners();
  tryLoadSchematic();

  // Show model name in header badge
  updateModelBadge();
});

function loadSettings() {
  AppState.apiKey        = localStorage.getItem('or_api_key') || '';
  AppState.model         = localStorage.getItem('or_model') || 'anthropic/claude-sonnet-4-5';
  AppState.temperature   = parseFloat(localStorage.getItem('or_temp') || '0.7');
  AppState.maxTokens     = parseInt(localStorage.getItem('or_max_tokens') || '4096');
  AppState.includeSchematicCtx = localStorage.getItem('or_schema_ctx') !== 'false';
  AppState.streamResponses     = localStorage.getItem('or_stream') !== 'false';
  AppState.lcscPreference      = localStorage.getItem('or_lcsc') !== 'false';

  // Apply to OpenRouter client
  orClient.setApiKey(AppState.apiKey);
  orClient.setModel(AppState.model);

  // Apply to form fields
  const apiKeyInput = document.getElementById('apiKeyInput');
  const modelSelect = document.getElementById('modelSelect');
  const tempSlider  = document.getElementById('tempSlider');
  const maxTokSel   = document.getElementById('maxTokensSelect');

  if (apiKeyInput) apiKeyInput.value = AppState.apiKey;
  if (modelSelect) modelSelect.value = AppState.model;
  if (tempSlider) {
    tempSlider.value = AppState.temperature;
    document.getElementById('tempValue').textContent = AppState.temperature;
  }
  if (maxTokSel) maxTokSel.value = AppState.maxTokens;

  setCheckbox('includeSchematicCtx', AppState.includeSchematicCtx);
  setCheckbox('streamResponses', AppState.streamResponses);
  setCheckbox('lcscPreference', AppState.lcscPreference);
}

function saveSettings() {
  AppState.apiKey       = document.getElementById('apiKeyInput')?.value.trim() || '';
  AppState.model        = document.getElementById('modelSelect')?.value || AppState.model;
  AppState.temperature  = parseFloat(document.getElementById('tempSlider')?.value || '0.7');
  AppState.maxTokens    = parseInt(document.getElementById('maxTokensSelect')?.value || '4096');
  AppState.includeSchematicCtx = document.getElementById('includeSchematicCtx')?.checked ?? true;
  AppState.streamResponses     = document.getElementById('streamResponses')?.checked ?? true;
  AppState.lcscPreference      = document.getElementById('lcscPreference')?.checked ?? true;

  localStorage.setItem('or_api_key',    AppState.apiKey);
  localStorage.setItem('or_model',      AppState.model);
  localStorage.setItem('or_temp',       AppState.temperature);
  localStorage.setItem('or_max_tokens', AppState.maxTokens);
  localStorage.setItem('or_schema_ctx', AppState.includeSchematicCtx);
  localStorage.setItem('or_stream',     AppState.streamResponses);
  localStorage.setItem('or_lcsc',       AppState.lcscPreference);

  orClient.setApiKey(AppState.apiKey);
  orClient.setModel(AppState.model);

  updateModelBadge();
  UI.toast('Settings saved', 'success');
}

function updateModelBadge() {
  const badge = document.getElementById('modelBadge');
  if (!badge) return;
  const shortName = AppState.model.split('/').pop() || AppState.model;
  badge.textContent = shortName;
  badge.title = AppState.model;
}

function setCheckbox(id, value) {
  const el = document.getElementById(id);
  if (el) el.checked = value;
}

async function tryLoadSchematic() {
  if (!EasyEDA.available) return;
  await Analyzer.loadSchematic();
}

// ── Event Listeners ───────────────────────────────────────────────────────────
function setupEventListeners() {
  // Tab navigation
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => UI.switchTab(btn.dataset.tab));
  });

  // Header actions
  document.getElementById('refreshSchematicBtn')?.addEventListener('click', () => Analyzer.loadSchematic());
  document.getElementById('clearChatBtn')?.addEventListener('click', clearChat);

  // Chat
  document.getElementById('sendBtn')?.addEventListener('click', sendChat);
  document.getElementById('chatInput')?.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') sendChat();
  });

  // Quick prompts
  document.querySelectorAll('.quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById('chatInput');
      if (input) { input.value = btn.dataset.prompt; input.focus(); }
    });
  });

  // Generate tab
  document.getElementById('generateBtn')?.addEventListener('click', runGenerate);
  document.getElementById('copyGenResult')?.addEventListener('click', () =>
    UI.copyToClipboard(Generator._lastRaw, 'Circuit design'));
  document.getElementById('applyToEasyEDA')?.addEventListener('click', applyToEasyEDA);

  // Generate voltage custom
  document.getElementById('genVoltage')?.addEventListener('change', e => {
    if (e.target.value === 'custom') {
      const v = prompt('Enter custom voltage (e.g. 9V, 15V):');
      if (v) e.target.value = v;
    }
  });

  // Analyze tab
  document.getElementById('loadSchematicBtn')?.addEventListener('click', () => Analyzer.loadSchematic());
  document.getElementById('analyzeBtn')?.addEventListener('click', runAnalyze);
  document.getElementById('copyAnalyzeResult')?.addEventListener('click', () =>
    UI.copyToClipboard(Analyzer.getLastReport(), 'Analysis report'));

  // BOM tab
  document.getElementById('bomFromSchematicBtn')?.addEventListener('click', () => {
    document.getElementById('bomManualInput').style.display = 'none';
    runBOM('schematic');
  });
  document.getElementById('bomManualBtn')?.addEventListener('click', () => {
    const input = document.getElementById('bomManualInput');
    input.style.display = input.style.display === 'none' ? 'block' : 'none';
  });
  document.getElementById('generateBOMBtn')?.addEventListener('click', () => {
    const manual = document.getElementById('bomManualText')?.value.trim();
    runBOM(manual ? 'manual' : 'schematic');
  });
  document.getElementById('copyBOMResult')?.addEventListener('click', () =>
    UI.copyToClipboard(AppState.lastBOM, 'BOM'));
  document.getElementById('downloadBOMResult')?.addEventListener('click', () =>
    UI.downloadText(AppState.lastBOM, 'bom.md'));

  // Settings
  document.getElementById('saveSettingsBtn')?.addEventListener('click', saveSettings);
  document.getElementById('tempSlider')?.addEventListener('input', e => {
    document.getElementById('tempValue').textContent = parseFloat(e.target.value).toFixed(2);
  });
  document.getElementById('toggleApiKey')?.addEventListener('click', e => {
    const input = document.getElementById('apiKeyInput');
    if (!input) return;
    const isPassword = input.type === 'password';
    input.type = isPassword ? 'text' : 'password';
    e.target.textContent = isPassword ? 'Hide' : 'Show';
  });
  document.getElementById('loadModelsBtn')?.addEventListener('click', loadAvailableModels);
}

// ── Chat ──────────────────────────────────────────────────────────────────────
async function sendChat() {
  if (AppState.isStreaming) {
    orClient.abort();
    AppState.isStreaming = false;
    UI.setStreaming(false);
    document.getElementById('sendBtn').textContent = '▶';
    return;
  }

  const input = document.getElementById('chatInput');
  const text = input?.value.trim();
  if (!text) return;
  if (!AppState.apiKey) {
    UI.toast('Add your OpenRouter API key in Settings', 'warning');
    UI.switchTab('settings');
    return;
  }

  // Clear input
  input.value = '';
  input.style.height = 'auto';

  // Remove welcome screen
  const welcome = document.querySelector('.welcome-msg');
  if (welcome) welcome.remove();

  // Append user message
  UI.appendUserMessage(text);

  // Build messages array
  AppState.chatHistory.push({ role: 'user', content: buildUserContent(text) });

  // Start streaming
  AppState.isStreaming = true;
  UI.setStreaming(true);
  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) sendBtn.textContent = '■';

  const bubble = UI.appendAssistantMessage();

  try {
    const fullText = await orClient.chat(
      AppState.chatHistory,
      {
        systemPrompt: buildSystemPrompt(),
        temperature: AppState.temperature,
        maxTokens: AppState.maxTokens,
        onChunk: (_, accumulated) => UI.updateStreamBubble(bubble, accumulated),
      }
    );

    UI.finalizeStreamBubble(bubble, fullText);
    AppState.chatHistory.push({ role: 'assistant', content: fullText });

    // Keep history to last 20 messages to avoid token bloat
    if (AppState.chatHistory.length > 20) {
      AppState.chatHistory = AppState.chatHistory.slice(-20);
    }
  } catch (e) {
    UI.finalizeStreamBubble(bubble, `**Error:** ${e.message}`);
    if (!e.message.includes('cancelled')) {
      UI.toast(e.message, 'error', 4000);
    }
  } finally {
    AppState.isStreaming = false;
    UI.setStreaming(false);
    if (sendBtn) sendBtn.textContent = '▶';
  }
}

function buildSystemPrompt() {
  let prompt = PROMPTS.CIRCUIT_EXPERT;
  if (AppState.lcscPreference) {
    prompt += '\n\nAlways prefer JLCPCB Basic Parts and include LCSC part numbers (C######) for every recommended component.';
  }
  return prompt;
}

function buildUserContent(text) {
  if (!AppState.includeSchematicCtx || !AppState.schematic?.parsed) return text;
  const ctx = EasyEDA.schematicToContext(AppState.schematic.parsed);
  if (ctx === 'No schematic loaded or schematic is empty.') return text;
  return `${text}\n\n---\n**Current Schematic Context:**\n${ctx}`;
}

function clearChat() {
  AppState.chatHistory = [];
  const container = document.getElementById('chatMessages');
  if (!container) return;
  container.innerHTML = `
    <div class="welcome-msg">
      <div class="welcome-icon">⚡</div>
      <h3>EasyEDA AI Copilot</h3>
      <p>Ask anything about circuit design, components, PCB layout, or EasyEDA.</p>
      <div class="quick-prompts">
        <button class="quick-btn" data-prompt="What decoupling capacitors should I add to my ESP32 circuit?">ESP32 decoupling caps</button>
        <button class="quick-btn" data-prompt="Explain the difference between LDO and buck converter for a 5V to 3.3V conversion">LDO vs Buck 5V→3.3V</button>
        <button class="quick-btn" data-prompt="What are best practices for high-speed PCB routing?">PCB routing tips</button>
        <button class="quick-btn" data-prompt="How do I protect my circuit from ESD?">ESD protection</button>
      </div>
    </div>`;
  document.querySelectorAll('.quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById('chatInput');
      if (input) { input.value = btn.dataset.prompt; input.focus(); }
    });
  });
  UI.toast('Chat cleared', 'info');
}

// ── Generate Tab ──────────────────────────────────────────────────────────────
async function runGenerate() {
  const description = document.getElementById('genDescription')?.value.trim();
  if (!description) { UI.toast('Please describe the circuit first', 'warning'); return; }
  if (!AppState.apiKey) { UI.toast('API key required — check Settings', 'warning'); UI.switchTab('settings'); return; }

  const btn = document.getElementById('generateBtn');
  UI.setLoading(btn, true);
  UI.setStreaming(true);

  const resultBox = document.getElementById('genResult');
  const resultContent = document.getElementById('genResultContent');
  if (resultBox) resultBox.style.display = 'none';

  try {
    const raw = await Generator.generate({
      description,
      voltage: document.getElementById('genVoltage')?.value,
      pcbStd: document.getElementById('genPCBStd')?.value,
      requirements: document.getElementById('genRequirements')?.value.trim(),
      temperature: AppState.temperature,
      maxTokens: AppState.maxTokens,
    });

    const parsed = Generator.parseCircuitJSON(raw);
    Generator.setLastResult(raw, parsed);

    if (resultContent) {
      resultContent.innerHTML = Generator.renderCircuitCard(parsed);
      // Append the full AI explanation below the card
      const extra = raw.replace(/```json[\s\S]*?```/, '').trim();
      if (extra) {
        const extraDiv = document.createElement('div');
        extraDiv.style.cssText = 'margin-top:12px;border-top:1px solid #373a40;padding-top:10px';
        extraDiv.innerHTML = UI.md(extra);
        resultContent.appendChild(extraDiv);
      }
    }
    if (resultBox) resultBox.style.display = 'block';
    UI.toast('Circuit generated!', 'success');
  } catch (e) {
    UI.toast(e.message, 'error', 4000);
  } finally {
    UI.setLoading(btn, false);
    UI.setStreaming(false);
  }
}

async function applyToEasyEDA() {
  if (!EasyEDA.available) {
    UI.toast('Not running inside EasyEDA — open as a Plugin', 'warning');
    return;
  }
  if (!Generator._lastCircuit) { UI.toast('Generate a circuit first', 'warning'); return; }

  const circuit = Generator._lastCircuit;
  const components = circuit.components || [];

  if (components.length === 0) { UI.toast('No components to place', 'warning'); return; }

  UI.toast(`Opening component search for ${components.length} parts…`, 'info');
  await EasyEDA.notify(`AI Copilot: Starting placement of ${components.length} components`);

  // Open EasyEDA component search for the first component
  try {
    await EasyEDA.openComponentSearch(components[0].value);
    UI.toast('Component panel opened — continue placement manually', 'info', 4000);
  } catch (e) {
    UI.toast('Could not open component panel: ' + e.message, 'error');
  }
}

// ── Analyze Tab ───────────────────────────────────────────────────────────────
async function runAnalyze() {
  if (!AppState.apiKey) { UI.toast('API key required — check Settings', 'warning'); UI.switchTab('settings'); return; }

  const btn = document.getElementById('analyzeBtn');
  const resultBox = document.getElementById('analyzeResult');
  const resultContent = document.getElementById('analyzeResultContent');

  UI.setLoading(btn, true);
  UI.setStreaming(true);
  if (resultBox) resultBox.style.display = 'none';

  try {
    // Ensure schematic is loaded
    if (!AppState.schematic?.parsed) {
      await Analyzer.loadSchematic();
    }

    const report = await Analyzer.analyze({
      checkDRC: document.getElementById('checkDRC')?.checked ?? true,
      checkBestPractices: document.getElementById('checkBestPractices')?.checked ?? true,
      checkComponents: document.getElementById('checkComponents')?.checked ?? true,
      checkPower: document.getElementById('checkPower')?.checked ?? true,
      temperature: AppState.temperature,
      maxTokens: AppState.maxTokens,
    });

    if (resultContent) resultContent.innerHTML = UI.md(report);
    if (resultBox) resultBox.style.display = 'block';
    UI.toast('Analysis complete', 'success');
  } catch (e) {
    UI.toast(e.message, 'error', 5000);
    if (resultContent) resultContent.innerHTML = `<p style="color:#ff6b6b">${e.message}</p>`;
    if (resultBox) resultBox.style.display = 'block';
  } finally {
    UI.setLoading(btn, false);
    UI.setStreaming(false);
  }
}

// ── BOM Tab ───────────────────────────────────────────────────────────────────
async function runBOM(source) {
  if (!AppState.apiKey) { UI.toast('API key required — check Settings', 'warning'); UI.switchTab('settings'); return; }

  const btn = document.getElementById('generateBOMBtn');
  const resultBox = document.getElementById('bomResult');
  const resultContent = document.getElementById('bomResultContent');

  UI.setLoading(btn, true);
  UI.setStreaming(true);
  if (resultBox) resultBox.style.display = 'none';

  try {
    let componentContext = '';

    if (source === 'schematic') {
      if (!AppState.schematic?.parsed) await Analyzer.loadSchematic();
      const parsed = AppState.schematic?.parsed;
      if (!parsed || parsed.componentCount === 0) {
        throw new Error('No components found in schematic. Load a schematic or use Manual Entry.');
      }
      componentContext = EasyEDA.schematicToContext(parsed);
    } else {
      componentContext = document.getElementById('bomManualText')?.value.trim() || '';
      if (!componentContext) throw new Error('Please describe your components in the manual entry box.');
    }

    const format = document.getElementById('bomFormat')?.value || 'jlcpcb';
    const extra = document.getElementById('bomExtra')?.value.trim() || '';

    const formatInstructions = {
      jlcpcb: 'Format as JLCPCB SMT Assembly BOM. Include LCSC part numbers and mark Basic/Extended parts.',
      csv: 'Format as CSV with headers: Ref Des,Qty,Value,Package,Description,LCSC #,Type,Notes',
      markdown: 'Format as a clean Markdown table.',
      mouser: 'Include Mouser and DigiKey part numbers as alternatives.',
    }[format] || '';

    const userMsg = [
      'Generate a professional BOM for the following components:',
      '',
      componentContext,
      '',
      formatInstructions,
      extra ? `Additional requirements: ${extra}` : '',
      '',
      AppState.lcscPreference ? 'Prioritize JLCPCB Basic Parts (no extra assembly fee).' : '',
    ].filter(Boolean).join('\n');

    let fullText = '';
    await orClient.chat(
      [{ role: 'user', content: userMsg }],
      {
        systemPrompt: PROMPTS.BOM_GENERATOR,
        temperature: 0.2,
        maxTokens: AppState.maxTokens,
        onChunk: (_, accumulated) => { fullText = accumulated; },
      }
    );

    AppState.lastBOM = fullText;
    if (resultContent) resultContent.innerHTML = UI.md(fullText);
    if (resultBox) resultBox.style.display = 'block';
    UI.toast('BOM generated!', 'success');
  } catch (e) {
    UI.toast(e.message, 'error', 4000);
  } finally {
    UI.setLoading(btn, false);
    UI.setStreaming(false);
  }
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function loadAvailableModels() {
  if (!AppState.apiKey) {
    UI.toast('Enter your API key first', 'warning');
    return;
  }

  const btn = document.getElementById('loadModelsBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }

  try {
    const models = await orClient.getModels();
    const select = document.getElementById('modelSelect');
    if (!select || models.length === 0) {
      UI.toast('No models returned', 'warning');
      return;
    }

    // Clear and rebuild the select with fetched models
    select.innerHTML = '';
    const byProvider = {};
    for (const m of models) {
      const provider = m.id.split('/')[0] || 'Other';
      if (!byProvider[provider]) byProvider[provider] = [];
      byProvider[provider].push(m);
    }

    for (const [provider, mods] of Object.entries(byProvider)) {
      const group = document.createElement('optgroup');
      group.label = provider.charAt(0).toUpperCase() + provider.slice(1);
      for (const m of mods) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.id.split('/').pop();
        if (m.id === AppState.model) opt.selected = true;
        group.appendChild(opt);
      }
      select.appendChild(group);
    }

    UI.toast(`Loaded ${models.length} models`, 'success');
  } catch (e) {
    UI.toast(`Failed to load models: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Load my available models'; }
  }
}
