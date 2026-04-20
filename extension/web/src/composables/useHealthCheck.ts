import { ref, onMounted, onUnmounted } from 'vue';
import { getApiUrl } from '../api/index';
import { fetchEda } from '../api/index';
import { useSettingsStore } from '../stores/settings-store';
import { makeLLmSettings } from '../utils/llm-settings';

export interface HealthStatus {
    connected: boolean;
    model: string | null;
    provider: string | null;
    version: string | null;
    error: string | null;
}

/**
 * Composable that polls the backend /api/health endpoint and returns
 * the connection status + currently configured AI model.
 */
export function useHealthCheck(intervalMs = 30000) {
    const status = ref<HealthStatus>({
        connected: false,
        model: null,
        provider: null,
        version: null,
        error: null,
    });

    const isChecking = ref(false);

    async function check() {
        if (isChecking.value) return;
        isChecking.value = true;
        try {
            const apiUrl = getApiUrl();

            // Send llmSettings so backend can report the active model
            let llmSettings: Record<string, any> = {};
            try {
                const settingsStore = useSettingsStore();
                llmSettings = makeLLmSettings(settingsStore);
            } catch (_) { /* settings store not ready yet */ }

            const res = await fetchEda(apiUrl + '/api/health', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ llmSettings }),
            });

            if (!res.ok) {
                status.value = {
                    connected: false,
                    model: null,
                    provider: null,
                    version: null,
                    error: `HTTP ${res.status}`,
                };
                return;
            }

            const data = await res.json();

            // Normalize model display name
            const rawModel: string = data.model || data.llm_model || '';
            let displayModel = rawModel;

            // Friendly model name mapping
            const modelMap: Record<string, string> = {
                'gpt-4o': 'GPT-4o',
                'gpt-4o-mini': 'GPT-4o Mini',
                'gpt-4-turbo': 'GPT-4 Turbo',
                'gpt-4': 'GPT-4',
                'gpt-3.5-turbo': 'GPT-3.5 Turbo',
                'claude-3-5-sonnet': 'Claude Sonnet 3.5',
                'claude-3-5-haiku': 'Claude Haiku 3.5',
                'claude-3-opus': 'Claude Opus 3',
                'claude-3-sonnet': 'Claude Sonnet 3',
                'claude-3-haiku': 'Claude Haiku 3',
                'gemini-1.5-pro': 'Gemini 1.5 Pro',
                'gemini-1.5-flash': 'Gemini 1.5 Flash',
                'deepseek-chat': 'DeepSeek Chat',
                'deepseek-coder': 'DeepSeek Coder',
            };

            for (const [key, name] of Object.entries(modelMap)) {
                if (rawModel.toLowerCase().includes(key.toLowerCase())) {
                    displayModel = name;
                    break;
                }
            }

            status.value = {
                connected: true,
                model: displayModel || 'Unknown Model',
                provider: data.provider || null,
                version: data.version || null,
                error: null,
            };
        } catch (err) {
            status.value = {
                connected: false,
                model: null,
                provider: null,
                version: null,
                error: err instanceof Error ? err.message : 'Connection failed',
            };
        } finally {
            isChecking.value = false;
        }
    }

    let timer: number | undefined;

    onMounted(() => {
        check();
        timer = window.setInterval(check, intervalMs);
    });

    onUnmounted(() => {
        if (timer !== undefined) clearInterval(timer);
    });

    return { status, isChecking, check };
}
