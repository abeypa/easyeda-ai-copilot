/**
 * UI utilities: markdown rendering, message rendering, toasts, tabs.
 */

const UI = {

  /** Configure marked.js renderer with copy buttons on code blocks. */
  initMarkdown() {
    if (typeof marked === 'undefined') return;

    marked.setOptions({
      breaks: true,
      gfm: true,
      highlight: (code, lang) => {
        if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
          return hljs.highlight(code, { language: lang }).value;
        }
        return typeof hljs !== 'undefined' ? hljs.highlightAuto(code).value : code;
      },
    });

    // Custom renderer to add copy button on pre blocks
    const renderer = new marked.Renderer();
    renderer.code = (code, language) => {
      const langClass = language ? ` class="language-${language}"` : '';
      const escapedCode = code
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      const highlighted = (() => {
        if (typeof hljs === 'undefined') return escapedCode;
        if (language && hljs.getLanguage(language)) {
          return hljs.highlight(code, { language }).value;
        }
        return hljs.highlightAuto(code).value;
      })();

      return `<pre style="position:relative"><code${langClass}>${highlighted}</code>` +
        `<button class="code-copy-btn" onclick="UI.copyCode(this)">Copy</button></pre>`;
    };

    marked.use({ renderer });
  },

  /** Render markdown string to HTML. */
  md(text) {
    if (typeof marked === 'undefined') {
      // Basic fallback: escape HTML, wrap code blocks
      return text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
    }
    return marked.parse(text);
  },

  /** Copy code block content. */
  copyCode(btn) {
    const code = btn.previousElementSibling?.textContent || '';
    navigator.clipboard.writeText(code).then(() => {
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
    });
  },

  /** Append a user message bubble to the chat. */
  appendUserMessage(text) {
    const container = document.getElementById('chatMessages');
    const el = document.createElement('div');
    el.className = 'message user';
    el.innerHTML = `
      <div class="msg-bubble">${this._escapeHtml(text)}</div>
      <div class="msg-meta">${this._timestamp()}</div>`;
    container.appendChild(el);
    this.scrollChat();
    return el;
  },

  /** Append an assistant message bubble and return the content element for streaming. */
  appendAssistantMessage(initialText = '') {
    const container = document.getElementById('chatMessages');
    const el = document.createElement('div');
    el.className = 'message assistant';
    el.innerHTML = `
      <div class="msg-bubble streaming-cursor" id="streamBubble">${initialText || '&nbsp;'}</div>
      <div class="msg-meta">${this._timestamp()}</div>`;
    container.appendChild(el);
    this.scrollChat();
    return el.querySelector('#streamBubble');
  },

  /** Update a streaming bubble with accumulated markdown content. */
  updateStreamBubble(bubble, fullText) {
    bubble.innerHTML = this.md(fullText);
    bubble.classList.add('streaming-cursor');
    this.scrollChat();
  },

  /** Finalize a streaming bubble (remove cursor, re-render markdown). */
  finalizeStreamBubble(bubble, fullText) {
    bubble.classList.remove('streaming-cursor');
    bubble.innerHTML = this.md(fullText);
    this.scrollChat();
  },

  /** Append a system/error notice. */
  appendNotice(text, type = 'info') {
    const container = document.getElementById('chatMessages');
    const colors = { info: '#4dabf7', error: '#ff6b6b', warning: '#ffd43b', success: '#51cf66' };
    const el = document.createElement('div');
    el.style.cssText = `text-align:center;padding:6px;font-size:11.5px;color:${colors[type] || colors.info}`;
    el.textContent = text;
    container.appendChild(el);
    this.scrollChat();
  },

  /** Scroll chat to bottom. */
  scrollChat() {
    const container = document.getElementById('chatMessages');
    if (container) container.scrollTop = container.scrollHeight;
  },

  /** Show a toast notification. */
  toast(message, type = 'info', duration = 2800) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, duration);
  },

  /** Switch the active tab. */
  switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `tab-${tabId}`);
    });
  },

  /** Render markdown into a result box and show it. */
  showResult(contentId, boxId, markdownText) {
    const content = document.getElementById(contentId);
    const box = document.getElementById(boxId);
    if (!content || !box) return;
    content.innerHTML = this.md(markdownText);
    box.style.display = 'block';
    content.scrollTop = 0;
  },

  /** Set loading state on a button. */
  setLoading(btn, loading, originalText) {
    if (!btn) return;
    btn.disabled = loading;
    if (loading) {
      btn.dataset.original = btn.textContent;
      btn.textContent = '⏳ Generating…';
    } else {
      btn.textContent = btn.dataset.original || originalText || btn.textContent;
    }
  },

  /** Toggle streaming indicator. */
  setStreaming(visible) {
    const el = document.getElementById('streamingIndicator');
    if (el) el.style.display = visible ? 'flex' : 'none';
  },

  /** Escape HTML for safe display. */
  _escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  },

  _timestamp() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  },

  /** Copy text to clipboard and show toast. */
  async copyToClipboard(text, label = 'Copied') {
    try {
      await navigator.clipboard.writeText(text);
      this.toast(`${label} to clipboard`, 'success');
    } catch (_) {
      // Fallback for older environments
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      this.toast(`${label} to clipboard`, 'success');
    }
  },

  /** Download text as a file. */
  downloadText(text, filename) {
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },
};
