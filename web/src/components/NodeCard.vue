<script setup lang="ts">
// The node card on the Studio canvas and in replay (n8n-style card, Make-style routing).
// Flat: hairline border, small radius, no shadow, no icon tile. Every node has a `done` and a
// `failed` output port. Wiring to Vue Flow handles is CP-31.
import { formatDuration } from '@/status'
import StatusBadge from './StatusBadge.vue'

defineProps<{
  title: string
  activity: string
  status?: string
  durationMs?: number | null
  selected?: boolean
}>()
</script>

<template>
  <article class="node" :class="{ 'node--selected': selected }" :aria-label="`${title}, ${activity}`">
    <div class="node__head">
      <strong class="node__title">{{ title }}</strong>
      <span class="node__activity">{{ activity }}</span>
    </div>
    <div v-if="status" class="node__run">
      <StatusBadge :status="status" />
      <span v-if="durationMs != null" class="node__time">{{ formatDuration(durationMs) }}</span>
    </div>
    <ul class="node__ports" aria-label="Output ports">
      <li><StatusBadge status="done" label="done" /></li>
      <li><StatusBadge status="failed" label="failed" /></li>
    </ul>
  </article>
</template>

<style scoped>
.node {
  display: grid;
  gap: var(--spacingVerticalS);
  width: 220px;
  padding: var(--spacingVerticalM) var(--spacingHorizontalM);
  border: var(--strokeWidthThin) solid var(--uaf-border-strong);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface);
}
.node--selected {
  border-color: var(--uaf-accent);
  box-shadow: 0 0 0 1px var(--uaf-accent);
}
.node__head {
  display: grid;
  min-width: 0;
}
.node__title,
.node__activity {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node__activity {
  color: var(--uaf-text-muted);
  font-family: var(--uaf-font-mono);
  font-size: var(--fontSizeBase200);
}
.node__run {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.node__time {
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
.node__ports {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacingHorizontalM);
  margin: 0;
  padding: var(--spacingVerticalS) 0 0;
  border-top: var(--strokeWidthThin) solid var(--uaf-border);
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
  list-style: none;
}
</style>
