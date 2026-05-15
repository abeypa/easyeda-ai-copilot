/**
 * EasyEDA API wrapper with safe fallbacks for standalone/dev use.
 * All methods return Promises and handle the callback-based EasyEDA API.
 */

const EasyEDA = {
  /** True when running inside EasyEDA plugin context. */
  get available() {
    return typeof api === 'function';
  },

  /** Wrap EasyEDA callback API into a Promise. */
  _call(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this.available) {
        reject(new Error('EasyEDA API not available (running outside EasyEDA).'));
        return;
      }
      try {
        api(method, params, (result) => resolve(result));
      } catch (e) {
        reject(e);
      }
    });
  },

  /** Get the full schematic source as JSON. */
  async getSchematic() {
    return this._call('getSource', { type: 'json' });
  },

  /** Get the schematic source as a string (raw EasyEDA format). */
  async getSchematicString() {
    return this._call('getSource', { type: 'string' });
  },

  /** Get currently selected components. */
  async getSelection() {
    return this._call('getSelectComponents');
  },

  /** Get canvas info (dimensions, origin). */
  async getCanvas() {
    return this._call('getCanvas');
  },

  /** Save the current schematic. */
  async save() {
    return this._call('save');
  },

  /** Get document info (title, uuid, etc.). */
  async getDocInfo() {
    return this._call('getDocDetail');
  },

  /**
   * Parse the schematic JSON and extract a component summary.
   * Returns { components, nets, componentCount, netCount }
   */
  parseSchematic(schematicJson) {
    const result = {
      components: [],
      nets: [],
      componentCount: 0,
      netCount: 0,
      rawJson: schematicJson,
    };

    if (!schematicJson) return result;

    let source = schematicJson;
    if (typeof source === 'string') {
      try { source = JSON.parse(source); } catch (_) { return result; }
    }

    const shapes = source.shape || source.schematics?.[0]?.dataStr?.shape || [];

    for (const shape of shapes) {
      if (typeof shape !== 'string') continue;

      // Library components: LIB~x~y~rotation~flip~...~reference~value~...
      if (shape.startsWith('LIB~') || shape.startsWith('SchLib~')) {
        const parts = shape.split('~');
        const ref = parts[7] || parts[6] || '';
        const value = parts[8] || parts[7] || '';
        if (ref && !ref.startsWith('gge')) {
          result.components.push({ ref, value, raw: shape.substring(0, 80) });
        }
      }

      // Net labels: N~x~y~rotation~id~label
      if (shape.startsWith('N~')) {
        const parts = shape.split('~');
        const label = parts[5] || '';
        if (label && !result.nets.includes(label)) {
          result.nets.push(label);
        }
      }
    }

    result.componentCount = result.components.length;
    result.netCount = result.nets.length;
    return result;
  },

  /**
   * Build a human-readable summary string of the schematic for AI context.
   */
  schematicToContext(parsed) {
    if (!parsed || parsed.componentCount === 0) {
      return 'No schematic loaded or schematic is empty.';
    }

    const lines = [
      `Schematic contains ${parsed.componentCount} components and ${parsed.netCount} nets.`,
      '',
      '## Components',
    ];

    for (const c of parsed.components.slice(0, 80)) {
      lines.push(`- ${c.ref}: ${c.value}`);
    }
    if (parsed.components.length > 80) {
      lines.push(`… and ${parsed.components.length - 80} more`);
    }

    if (parsed.nets.length > 0) {
      lines.push('', '## Power/Signal Nets');
      lines.push(parsed.nets.join(', '));
    }

    return lines.join('\n');
  },

  /**
   * Apply a generated component list to EasyEDA by opening the search panel.
   * Since programmatic placement requires exact coordinates, we guide the user.
   */
  async openComponentSearch(componentRef) {
    return this._call('openComponentPanel', { keyword: componentRef });
  },

  /** Show a message inside EasyEDA's notification system. */
  async notify(message) {
    if (this.available) {
      try { api('showMessage', { message }); } catch (_) {}
    }
  },
};
