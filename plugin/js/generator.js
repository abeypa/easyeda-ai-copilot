/**
 * Circuit Generator — converts AI JSON output into actionable guidance
 * and attempts EasyEDA API component placement where possible.
 */

const Generator = {

  /** Parse the JSON circuit block from AI markdown output. */
  parseCircuitJSON(aiOutput) {
    const match = aiOutput.match(/```json\s*([\s\S]*?)```/);
    if (!match) return null;
    try {
      return JSON.parse(match[1].trim());
    } catch (e) {
      console.warn('Failed to parse circuit JSON:', e);
      return null;
    }
  },

  /** Render a circuit JSON object into an HTML card for display. */
  renderCircuitCard(circuit) {
    if (!circuit) return '<p style="color:#ff6b6b">No structured circuit data found.</p>';

    const componentRows = (circuit.components || []).map(c => `
      <tr>
        <td>${this._esc(c.ref)}</td>
        <td>${c.quantity || 1}</td>
        <td>${this._esc(c.value)}</td>
        <td>${this._esc(c.package || '')}</td>
        <td>${this._esc(c.description || '')}</td>
        <td>${c.lcsc
          ? `<a href="https://www.lcsc.com/product-detail/${c.lcsc}.html"
               target="_blank" style="color:#4dabf7">${c.lcsc}</a>`
          : '—'}</td>
      </tr>`).join('');

    const netRows = (circuit.nets || []).map(n => `
      <tr>
        <td><strong>${this._esc(n.name)}</strong></td>
        <td>${(n.connections || []).join(', ')}</td>
      </tr>`).join('');

    const notes = (circuit.design_notes || [])
      .map(n => `<li>${this._esc(n)}</li>`).join('');

    return `
      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <strong style="color:#4dabf7;font-size:14px">${this._esc(circuit.title || 'Generated Circuit')}</strong>
          <p style="color:#9ca3af;font-size:11.5px;margin-top:4px">${this._esc(circuit.description || '')}</p>
          ${circuit.supply_voltage ? `<span style="background:#2c2e33;border:1px solid #373a40;border-radius:4px;padding:2px 8px;font-size:11px">Supply: ${circuit.supply_voltage}</span>` : ''}
        </div>

        ${componentRows ? `
        <div>
          <div style="font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Components (${(circuit.components || []).length})</div>
          <div style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;font-size:11.5px">
              <thead>
                <tr style="background:#2c2e33">
                  <th style="padding:5px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">Ref</th>
                  <th style="padding:5px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">Qty</th>
                  <th style="padding:5px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">Value</th>
                  <th style="padding:5px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">Package</th>
                  <th style="padding:5px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">Description</th>
                  <th style="padding:5px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">LCSC</th>
                </tr>
              </thead>
              <tbody>${componentRows}</tbody>
            </table>
          </div>
        </div>` : ''}

        ${netRows ? `
        <div>
          <div style="font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Netlists</div>
          <table style="width:100%;border-collapse:collapse;font-size:11.5px">
            <thead>
              <tr style="background:#2c2e33">
                <th style="padding:4px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">Net</th>
                <th style="padding:4px 8px;text-align:left;border:1px solid #373a40;color:#9ca3af">Connections</th>
              </tr>
            </thead>
            <tbody>${netRows}</tbody>
          </table>
        </div>` : ''}

        ${notes ? `
        <div>
          <div style="font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Design Notes</div>
          <ul style="padding-left:16px;font-size:12px;line-height:1.6;color:#c9cdd3">${notes}</ul>
        </div>` : ''}

        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="sm-btn" onclick="Generator.exportKicadNetlist()">Export KiCad Netlist</button>
          <button class="sm-btn" onclick="Generator.exportCSV()">Export CSV BOM</button>
          <button class="sm-btn primary" onclick="Generator.openLCSCSearch()">Search LCSC Parts ↗</button>
        </div>
      </div>`;
  },

  /** Generate circuit from user description using OpenRouter. */
  async generate({ description, voltage, pcbStd, requirements, temperature, maxTokens }) {
    const userMsg = [
      `Design a circuit with the following requirements:`,
      ``,
      `**Description:** ${description}`,
      voltage ? `**Supply Voltage:** ${voltage}` : '',
      pcbStd ? `**PCB Standard:** ${pcbStd}` : '',
      requirements ? `**Special Requirements:** ${requirements}` : '',
    ].filter(Boolean).join('\n');

    let fullText = '';
    await orClient.chat(
      [{ role: 'user', content: userMsg }],
      {
        systemPrompt: PROMPTS.SCHEMATIC_GENERATOR,
        temperature: temperature ?? 0.4,
        maxTokens: maxTokens ?? 4096,
        onChunk: (delta, accumulated) => { fullText = accumulated; },
      }
    );
    return fullText;
  },

  /** Store last generated circuit for export functions. */
  _lastCircuit: null,
  _lastRaw: '',

  setLastResult(raw, parsed) {
    this._lastRaw = raw;
    this._lastCircuit = parsed;
  },

  exportKicadNetlist() {
    if (!this._lastCircuit) { UI.toast('No circuit generated yet', 'warning'); return; }
    const c = this._lastCircuit;
    let netlist = `(export (version D)\n  (design\n    (title "${c.title || 'Generated'}")\n  )\n  (components\n`;
    for (const comp of (c.components || [])) {
      netlist += `    (comp (ref "${comp.ref}")\n      (value "${comp.value}")\n      (footprint "${comp.package || ''}")\n    )\n`;
    }
    netlist += `  )\n)\n`;
    UI.downloadText(netlist, `${(c.title || 'circuit').replace(/\s+/g, '_')}_netlist.kicad`);
    UI.toast('KiCad netlist downloaded', 'success');
  },

  exportCSV() {
    if (!this._lastCircuit) { UI.toast('No circuit generated yet', 'warning'); return; }
    const rows = [['Ref', 'Qty', 'Value', 'Package', 'Description', 'LCSC']];
    for (const c of (this._lastCircuit.components || [])) {
      rows.push([c.ref, c.quantity || 1, c.value, c.package || '', c.description || '', c.lcsc || '']);
    }
    const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
    UI.downloadText(csv, `${(this._lastCircuit.title || 'bom').replace(/\s+/g, '_')}_bom.csv`);
    UI.toast('BOM CSV downloaded', 'success');
  },

  openLCSCSearch() {
    if (!this._lastCircuit?.components?.length) { UI.toast('No components to search', 'warning'); return; }
    const firstLCSC = this._lastCircuit.components.find(c => c.lcsc)?.lcsc;
    const url = firstLCSC
      ? `https://www.lcsc.com/product-detail/${firstLCSC}.html`
      : 'https://www.lcsc.com/';
    window.open(url, '_blank');
  },

  _esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  },
};
