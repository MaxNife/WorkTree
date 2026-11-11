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
    <li
      v-for="step in steps"
      :key="step.id"
      class="run-timeline__item"
      :class="`run-timeline__item--${statusStyle(step.state).kind}`"
      :data-state="step.state"
    >
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
/* A vine down the left: each step is a bud on one stem, coloured by its state. The status word on
   the right still says what the colour means. */
.run-timeline {
  list-style: none;
  margin: 0;
  padding: var(--space-4) 0;
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius-container);
  background: var(--wt-surface);
}
.run-timeline__empty {
  margin: 0;
  color: var(--wt-muted);
}
.run-timeline__item {
  position: relative;
  padding-left: var(--space-32);
}
.run-timeline__item::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 15px;
  width: var(--stroke-2);
  background: var(--wt-line);
}
.run-timeline__item:first-child::before {
  top: calc(var(--wt-row-height) / 2);
}
.run-timeline__item:last-child::before {
  bottom: auto;
  height: calc(var(--wt-row-height) / 2);
}
.run-timeline__item:only-child::before {
  display: none;
}
.run-timeline__item::after {
  content: '';
  position: absolute;
  top: calc(var(--wt-row-height) / 2 - 6px);
  left: 10px;
  width: 12px;
  height: 12px;
  box-sizing: border-box;
  border: var(--stroke-2) solid var(--bud);
  border-radius: var(--radius-full);
  background: var(--bud);
  box-shadow: 0 0 0 3px var(--wt-surface);
}
.run-timeline__item--ok {
  --bud: var(--wt-ok);
}
.run-timeline__item--danger {
  --bud: var(--wt-danger);
}
.run-timeline__item--warn {
  --bud: var(--wt-warn);
}
.run-timeline__item--attention {
  --bud: var(--wt-attention);
}
.run-timeline__item--running {
  --bud: var(--wt-accent-text);
}
.run-timeline__item--neutral {
  --bud: var(--wt-muted);
}
.run-timeline__item--neutral::after {
  background: var(--wt-surface);
}
/* Fixed columns, because each row is its own grid and they still have to line up. */
.run-timeline__summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) 10ch minmax(11ch, max-content) 9ch;
  align-items: center;
  gap: var(--space-12);
  min-height: var(--wt-row-height);
  margin-right: var(--space-4);
  padding: var(--wt-cell-padding);
  border-radius: var(--wt-radius);
  list-style: none;
  cursor: pointer;
}
.run-timeline__summary::-webkit-details-marker {
  display: none;
}
.run-timeline__summary:hover {
  background: var(--wt-surface-hover);
}
.run-timeline__summary:focus-visible {
  outline-offset: calc(-1 * var(--wt-focus-width));
}
.run-timeline__chevron {
  color: var(--wt-muted);
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
  color: var(--wt-muted);
  font-size: var(--font-size-12);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.run-timeline__body {
  display: grid;
  gap: var(--space-8);
  min-width: 0;
  margin: 0 var(--space-12) var(--space-8) var(--space-8);
  padding: var(--space-10) var(--space-12);
  border-radius: var(--wt-radius);
  background: var(--wt-sunken);
  overflow-wrap: anywhere;
}
.run-timeline__message {
  margin: 0;
  color: var(--wt-muted);
}
.run-timeline__message--failed {
  color: var(--wt-danger);
}
@media (forced-colors: active) {
  .run-timeline__item::after {
    forced-color-adjust: none;
    border-color: CanvasText;
    background: CanvasText;
  }
  .run-timeline__item--neutral::after {
    background: Canvas;
  }
}
</style>
