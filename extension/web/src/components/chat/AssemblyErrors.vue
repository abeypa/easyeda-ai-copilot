<template>
  <div v-if="errors && errors.length > 0" class="assembly-errors">
    <div class="errors-header">
      <span class="errors-title">Assembly Notices</span>
      <span class="errors-count">{{ errors.length }}</span>
    </div>
    <div class="errors-list">
      <div
        v-for="(error, idx) in errors"
        :key="idx"
        class="error-item"
        :class="[`severity-${error.severity || 'info'}`]"
      >
        <div class="error-icon">
          <span v-if="(error.severity || 'info') === 'error'" title="Error">✕</span>
          <span v-else-if="error.severity === 'warning'" title="Warning">⚠</span>
          <span v-else title="Info">ℹ</span>
        </div>
        <div class="error-body">
          <span class="error-component" v-if="error.component">{{ error.component }}</span>
          <span class="error-message">{{ error.message || error.error }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface AssemblyError {
  component?: string;
  message?: string;
  error?: string;
  /** 'info' | 'warning' | 'error' */
  severity?: 'info' | 'warning' | 'error';
}

defineProps<{
  errors: AssemblyError[];
}>();
</script>

<style scoped>
.assembly-errors {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  margin-top: 0.75rem;
  overflow: hidden;
  font-size: 0.8rem;
}

.errors-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.75rem;
  background: var(--color-background-secondary);
  border-bottom: 1px solid var(--color-border);
}

.errors-title {
  font-weight: 600;
  color: var(--color-text);
  font-size: 0.75rem;
}

.errors-count {
  background: var(--color-border-dark);
  color: var(--color-text-tertiary);
  border-radius: 10px;
  padding: 0 6px;
  font-size: 0.7rem;
}

.errors-list {
  max-height: 180px;
  overflow-y: auto;
}

.error-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.4rem 0.75rem;
  border-bottom: 1px solid var(--color-border);
  transition: background 0.15s;
}

.error-item:last-child {
  border-bottom: none;
}

.error-item.severity-info {
  background: rgba(59, 130, 246, 0.06);
  border-left: 3px solid #3b82f6;
}

.error-item.severity-warning {
  background: rgba(234, 179, 8, 0.06);
  border-left: 3px solid #eab308;
}

.error-item.severity-error {
  background: rgba(239, 68, 68, 0.06);
  border-left: 3px solid #ef4444;
}

.error-icon {
  font-size: 0.85rem;
  min-width: 16px;
  text-align: center;
  line-height: 1.4;
}

.severity-info .error-icon { color: #3b82f6; }
.severity-warning .error-icon { color: #eab308; }
.severity-error .error-icon { color: #ef4444; }

.error-body {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}

.error-component {
  font-weight: 600;
  color: var(--color-text);
  font-size: 0.75rem;
}

.error-message {
  color: var(--color-text-secondary);
  word-break: break-word;
  line-height: 1.4;
}
</style>
