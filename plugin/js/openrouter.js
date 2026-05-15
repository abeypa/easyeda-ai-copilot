/**
 * OpenRouter API client with streaming support.
 * Handles all communication with openrouter.ai/api/v1
 */

class OpenRouterClient {
  constructor(apiKey = '', model = 'anthropic/claude-3.5-sonnet') {
    this.apiKey = apiKey;
    this.model = model;
    this.baseUrl = 'https://openrouter.ai/api/v1';
    this.abortController = null;
  }

  setApiKey(key) { this.apiKey = key; }
  setModel(model) { this.model = model; }

  /** Stream a chat completion. Calls onChunk(delta, fullText) for each token. */
  async chat(messages, { onChunk, temperature = 0.7, maxTokens = 4096, systemPrompt } = {}) {
    if (!this.apiKey) throw new Error('OpenRouter API key not set. Go to Settings to add your key.');

    // Abort any previous in-flight request
    if (this.abortController) this.abortController.abort();
    this.abortController = new AbortController();

    const payload = {
      model: this.model,
      messages: systemPrompt
        ? [{ role: 'system', content: systemPrompt }, ...messages]
        : messages,
      stream: true,
      temperature,
      max_tokens: maxTokens,
    };

    let response;
    try {
      response = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': 'https://easyeda.com',
          'X-Title': 'EasyEDA AI Copilot',
        },
        body: JSON.stringify(payload),
        signal: this.abortController.signal,
      });
    } catch (err) {
      if (err.name === 'AbortError') throw new Error('Request cancelled.');
      throw new Error(`Network error: ${err.message}`);
    }

    if (!response.ok) {
      let errMsg = `HTTP ${response.status}`;
      try {
        const errBody = await response.json();
        errMsg = errBody.error?.message || errBody.message || errMsg;
      } catch (_) {}
      throw new Error(`OpenRouter error: ${errMsg}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let fullText = '';
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      // Keep last (possibly incomplete) line in buffer
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data: ')) continue;

        const data = trimmed.slice(6);
        if (data === '[DONE]') continue;

        try {
          const parsed = JSON.parse(data);
          const delta = parsed.choices?.[0]?.delta?.content || '';
          if (delta) {
            fullText += delta;
            onChunk?.(delta, fullText);
          }
        } catch (_) {
          // Ignore malformed SSE chunks
        }
      }
    }

    this.abortController = null;
    return fullText;
  }

  /** Non-streaming single completion (for structured JSON output). */
  async complete(messages, { temperature = 0.3, maxTokens = 4096, systemPrompt } = {}) {
    if (!this.apiKey) throw new Error('OpenRouter API key not set.');

    const payload = {
      model: this.model,
      messages: systemPrompt
        ? [{ role: 'system', content: systemPrompt }, ...messages]
        : messages,
      stream: false,
      temperature,
      max_tokens: maxTokens,
    };

    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://easyeda.com',
        'X-Title': 'EasyEDA AI Copilot',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let errMsg = `HTTP ${response.status}`;
      try { const b = await response.json(); errMsg = b.error?.message || errMsg; } catch (_) {}
      throw new Error(`OpenRouter error: ${errMsg}`);
    }

    const data = await response.json();
    return data.choices?.[0]?.message?.content || '';
  }

  /** Fetch available models for this API key. */
  async getModels() {
    if (!this.apiKey) throw new Error('API key required to fetch models.');

    const response = await fetch(`${this.baseUrl}/models`, {
      headers: { 'Authorization': `Bearer ${this.apiKey}` },
    });

    if (!response.ok) throw new Error(`Failed to fetch models: HTTP ${response.status}`);
    const data = await response.json();
    return (data.data || []).sort((a, b) => a.id.localeCompare(b.id));
  }

  /** Validate API key by calling /auth/key endpoint. */
  async validateKey(key) {
    const response = await fetch(`${this.baseUrl}/auth/key`, {
      headers: { 'Authorization': `Bearer ${key}` },
    });
    if (!response.ok) return { valid: false, error: `HTTP ${response.status}` };
    const data = await response.json();
    return {
      valid: true,
      label: data.data?.label || 'API Key',
      creditLimit: data.data?.limit,
      usage: data.data?.usage,
    };
  }

  /** Cancel any in-flight streaming request. */
  abort() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
  }
}

// Global singleton
const orClient = new OpenRouterClient();
