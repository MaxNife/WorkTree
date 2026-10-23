<script setup lang="ts">
// GitHub Actions-style step list: one collapsible row per step with state, attempts and duration.
// Failed steps start open. The body of each step (logs, outputs) comes from the `detail` slot.
import { formatDuration, statusStyle } from '@/status'
import StatusBadge from './StatusBadge.vue'

export interface TimelineStep {
  id: string
  name: string
  state: string
  durationMs?: number | null
  attempts?: number
  message?: string | null
}
defineProps<{ steps: TimelineStep[] }>()
</script>

<template>
  <ol class="run-timeline" aria-label="Run steps">
    <li v-for="step in steps" :key="step.id" class="run-timeline__item" :data-state="step.state">
      <details :open="statusStyle(step.state).kind === 'danger' || undefined">
        <summary class="run-timeline__summary">
          <span class="run-timeline__name">{{ step.name }}</span>
          <span v-if="(step.attempts ?? 1) > 1" class="run-timeline__attempts">attempt {{ step.attempts }}</span>
          <StatusBadge :status="step.state" />
          <span class="run-timeline__time">{{ formatDuration(step.durationMs) }}</span>
        </summary>
        <div class="run-timeline__body">
          <p v-if="step.message" class="run-timeline__message">{{ step.message }}</p>
          <slot name="detail" :step="step" />
        </div>
      </details>
    </li>
  </ol>
</template>

<style scoped>
.run-timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  border: var(--strokeWidthThin) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
}
.run-timeline__item + .run-timeline__item {
  border-top: var(--strokeWidthThin) solid var(--uaf-border);
}
.run-timeline__summary {
  display: grid;
  grid-template-columns: 1fr auto auto 72px;
  align-items: center;
  gap: var(--spacingHorizontalM);
  min-height: var(--uaf-row-height);
  padding: var(--uaf-cell-padding);
  cursor: pointer;
}
.run-timeline__summary:hover {
  background: var(--uaf-surface-hover);
}
.run-timeline__name {
  font-weight: var(--fontWeightSemibold);
}
.run-timeline__attempts,
.run-timeline__time {
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
.run-timeline__time {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.run-timeline__body {
  padding: var(--uaf-cell-padding);
  background: var(--uaf-surface-sunken);
}
.run-timeline__message {
  margin: 0 0 var(--spacingVerticalS);
  color: var(--uaf-danger);
}
</style>
