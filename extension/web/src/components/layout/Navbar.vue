<template>
  <div class="navbar">
    <div class="tabs">
      <IconButton :class="['tab', { active: activeTab === 'chat' }]" @click="store.setActiveTab('chat')"
        icon="MessageSquare">
        <span>Chat</span>
      </IconButton>
      <IconButton :class="['tab', { active: activeTab === 'completions' }]" @click="store.setActiveTab('completions')"
        icon="CircleCheckBig">
        <span>Completions</span>
      </IconButton>
      <IconButton :class="['tab', { active: activeTab === 'simulate' }]" @click="store.setActiveTab('simulate')"
        icon="Play">
        <span>Simulate</span>
      </IconButton>
      <IconButton :class="['tab', { active: activeTab === 'pcb' }]" @click="store.setActiveTab('pcb')"
        icon="CircuitBoard">
        <span>PCB</span>
      </IconButton>
      <IconButton :class="['tab', { active: activeTab === 'settings' }]" @click="store.setActiveTab('settings')"
        icon="Settings">
        <span>Settings</span>
      </IconButton>
    </div>

    <div class="nav-controls" @click.stop>
      <!-- Model indicator: green dot + model name when connected, red dot when not -->
      <div class="model-indicator" :title="modelTitle">
        <span class="status-dot" :class="{ connected: health.connected, disconnected: !health.connected }"></span>
        <span v-if="health.connected && health.model" class="model-name">{{ health.model }}</span>
        <span v-else-if="!health.connected" class="model-name offline">Offline</span>
      </div>

      <slot name="controls"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useAppStore } from '../../stores/app-store';
import IconButton from '../shared/IconButton.vue';
import { useHealthCheck } from '../../composables/useHealthCheck';

const store = useAppStore();
const activeTab = computed(() => store.activeTab);

const { status: health } = useHealthCheck(20000);

const modelTitle = computed(() => {
  if (health.value.connected) {
    return `Connected to backend — Model: ${health.value.model}${health.value.provider ? ' via ' + health.value.provider : ''}`;
  }
  return `Backend offline: ${health.value.error || 'Cannot connect to localhost:5120'}`;
});
</script>

<style scoped>
.navbar {
  background-color: var(--color-background);
  display: flex;
  border-bottom: 1px solid var(--color-border);
  min-height: 32px;
  max-height: 32px;
  align-items: center;
}

.nav-controls {
  display: flex;
  align-items: center;
  margin-left: auto;
  padding: 0.5rem;
  gap: 0.5rem;
}

.tabs {
  display: flex;
  gap: 0.1rem;
}

.tab {
  padding: 3px 8px;
  border-radius: 0;
  font-size: 11px;
}

.tab.active {
  color: var(--color-primary);
  border-bottom: 2px solid var(--color-primary);
}

/* Model status indicator */
.model-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--color-text-tertiary);
  cursor: default;
  user-select: none;
  white-space: nowrap;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.connected {
  background-color: #22c55e;
  box-shadow: 0 0 4px #22c55e80;
}

.status-dot.disconnected {
  background-color: #ef4444;
  box-shadow: 0 0 4px #ef444480;
}

.model-name {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
}

.model-name.offline {
  color: var(--color-text-tertiary);
}
</style>
