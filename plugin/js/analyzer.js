/**
 * Schematic Analyzer — reads current EasyEDA schematic and sends to AI for review.
 */

const Analyzer = {

  _lastReport: '',

  /** Load and parse the current schematic from EasyEDA. */
  async loadSchematic() {
    const dot = document.getElementById('ctxDot');
    const label = document.getElementById('ctxLabel');

    if (dot) dot.className = 'ctx-dot loading';
    if (label) label.textContent = 'Loading schematic…';

    try {
      const raw = await EasyEDA.getSchematic();
      const parsed = EasyEDA.parseSchematic(raw);

      AppState.schematic = { raw, parsed };

      if (parsed.componentCount > 0) {
        if (dot) dot.className = 'ctx-dot active';
        if (label) label.textContent = `${parsed.componentCount} components, ${parsed.netCount} nets`;
        this._renderSchematicPreview(parsed);
      } else {
        if (dot) dot.className = 'ctx-dot';
        if (label) label.textContent = 'Schematic appears empty';
        this._showEmptyPreview();
      }
      return parsed;
    } catch (e) {
      if (dot) dot.className = 'ctx-dot';
      if (label) label.textContent = EasyEDA.available ? 'Failed to load' : 'Not in EasyEDA';
      this._showEmptyPreview();
      return null;
    }
  },

  /** Render a schematic summary card in the Analyze tab. */
  _renderSchematicPreview(parsed) {
    const preview = document.getElementById('schematicPreview');
    if (!preview) return;

    const chips = parsed.components.slice(0, 12)
      .map(c => `<span class="comp-chip">${c.ref}: ${c.value}</span>`)
      .join('');
    const more = parsed.components.length > 12
      ? `<span class="comp-chip" style="color:#6b7280">+${parsed.components.length - 12} more</span>`
      : '';

    preview.innerHTML = `
      <div class="schematic-summary">
        <div class="comp-count">
          📐 <strong>${parsed.componentCount}</strong> components &nbsp;|&nbsp;
          🔗 <strong>${parsed.netCount}</strong> nets
        </div>
        <div class="comp-chips">${chips}${more}</div>
      </div>`;
  },

  _showEmptyPreview() {
    const preview = document.getElementById('schematicPreview');
    if (!preview) return;
    preview.innerHTML = `
      <div class="preview-empty">
        <span>📐</span>
        <p>No schematic loaded</p>
        <button class="sm-btn" id="loadSchematicBtn">Load from EasyEDA</button>
      </div>`;
    document.getElementById('loadSchematicBtn')?.addEventListener('click', () => this.loadSchematic());
  },

  /** Run AI analysis on the current schematic. */
  async analyze({ checkDRC, checkBestPractices, checkComponents, checkPower, temperature, maxTokens }) {
    const parsed = AppState.schematic?.parsed;
    if (!parsed || parsed.componentCount === 0) {
      throw new Error('No schematic loaded. Click "Load from EasyEDA" first.');
    }

    const context = EasyEDA.schematicToContext(parsed);

    const checks = [];
    if (checkDRC) checks.push('Design Rule Checks (floating nets, short circuits, missing connections)');
    if (checkBestPractices) checks.push('Best Practices (decoupling caps, pull-ups, test points)');
    if (checkComponents) checks.push('Component Selection (values, ratings, LCSC availability)');
    if (checkPower) checks.push('Power & Safety (voltage levels, current ratings, protection)');

    const userMsg = [
      'Please analyze the following EasyEDA schematic:',
      '',
      '```',
      context,
      '```',
      '',
      `Focus on: ${checks.join(', ')}.`,
      '',
      'Provide a detailed, structured analysis report.',
    ].join('\n');

    let fullText = '';
    await orClient.chat(
      [{ role: 'user', content: userMsg }],
      {
        systemPrompt: PROMPTS.SCHEMATIC_ANALYZER,
        temperature: temperature ?? 0.3,
        maxTokens: maxTokens ?? 4096,
        onChunk: (_, accumulated) => { fullText = accumulated; },
      }
    );

    this._lastReport = fullText;
    return fullText;
  },

  getLastReport() { return this._lastReport; },
};
