<script setup lang="ts">
// GitHub Actions-style step list: one collapsible row per step with state, attempts and duration.
// Failed steps start open. The body of each step (logs, outputs) comes from the `detail` slot.
import { formatDuration, statusStyle } from '@/status'
import StatusBadge from './StatusBadge.vue'
import UIcon from './UIcon.vue'

export interface TimelineStep {
  id: string
  name: string
  state: string
  durationMs?: number | null
  attempts?: number
  message?: string | null
}
withDefaults(defineProps<{ steps: TimelineStep[]; label?: string }>(), { label: 'Run steps' })

const failed = (step: TimelineStep): boolean => statusStyle(step.state).kind === 'danger'
</script>

<template>
  <p v-if="steps.length === 0" class="run-timeline__empty">No steps yet.</p>
  <ol v-else class="run-timeline" :aria-label="label">
    <li v-for="step in steps" :key="step.id" class="run-timeline__item" :data-state="step.state">
      <details :open="failed(step) || undefined">
        <summary class="run-timeline__summary">
          <UIcon class="run-timeline__chevron" name="chevron-right" />
          <span class="run-timeline__name">{{ step.name }}</span>
          <span class="run-timeline__meta">{{ (step.attempts ?? 1) > 1 ? `attempt ${step.attempts}` : '' }}</span>
          <StatusBadge :status="step.state" />
          <span class="run-timeline__meta">{{ formatDuration(step.durationMs) }}</span>
        </summary>
        <div class="run-timeline__body">
          <p v-if="step.message" class="run-timeline__message" :class="{ 'run-timeline__message--failed': failed(step) }">
            {{ step.message }}
          </p>
          <slot name="detail" :step="step">
            <p v-if="!step.message" class="run-timeline__message">No details for this step.</p>
          </slot>
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
  border: var(--stroke-1) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
}
.run-timeline__empty {
  margin: 0;
  color: var(--uaf-text-muted);
}
.run-timeline__item + .run-timeline__item {
  border-top: var(--stroke-1) solid var(--uaf-border);
}
/* Fixed columns, because each row is its own grid and they still have to line up. */
.run-timeline__summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) 10ch minmax(11ch, max-content) 9ch;
  align-items: center;
  gap: var(--space-12);
  min-height: var(--uaf-row-height);
  padding: var(--uaf-cell-padding);
  cursor: pointer;
}
.run-timeline__summary:hover {
  background: var(--uaf-surface-hover);
}
/* Drawn inside the row, so the rows above and below do not cover it. */
.run-timeline__summary:focus-visible {
  outline-offset: calc(-1 * var(--uaf-focus-width));
}
.run-timeline__chevron {
  color: var(--uaf-text-muted);
  transition: transform var(--duration-fast) var(--ease-standard);
}
details[open] > .run-timeline__summary .run-timeline__chevron {
  transform: rotate(90deg);
}
.run-timeline__name {
  font-weight: var(--weight-semibold);
  overflow-wrap: anywhere;
}
.run-timeline__meta {
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.run-timeline__body {
  display: grid;
  gap: var(--space-8);
  min-width: 0;
  padding: var(--uaf-cell-padding);
  background: var(--uaf-surface-sunken);
  overflow-wrap: anywhere;
}
.run-timeline__message {
  margin: 0;
  color: var(--uaf-text-muted);
}
.run-timeline__message--failed {
  color: var(--uaf-danger);
}
</style>
