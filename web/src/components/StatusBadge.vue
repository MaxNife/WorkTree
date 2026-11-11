<script setup lang="ts">
// A status mark plus its word: no pill, border or tinted fill. Each kind has its own shape as well as
// its own colour (a tick, a cross, a clock, an alert, a turning ring, a hollow ring), and the word is
// always shown, so colour is never the only signal.
import { computed } from 'vue'
import type { IconName } from '@/icons/paths'
import { statusStyle, type StatusKind } from '@/status'
import UIcon from './UIcon.vue'

const props = defineProps<{ status: string; label?: string }>()
const style = computed(() => statusStyle(props.status))
const text = computed(() => props.label ?? style.value.label)

const MARKS: Partial<Record<StatusKind, IconName>> = {
  ok: 'check-circle',
  danger: 'dismiss-circle',
  warn: 'clock',
  attention: 'error',
}
const mark = computed(() => MARKS[style.value.kind])
</script>

<template>
  <span class="status" :class="`status--${style.kind}`" :data-status="status">
    <span class="status__dot" aria-hidden="true">
      <UIcon v-if="mark" :name="mark" :size="14" weight="fill" />
      <span v-else class="status__ring" :class="`status__ring--${style.kind}`" />
    </span>
    <span class="status__word">{{ text }}</span>
  </span>
</template>

<style scoped>
.status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  white-space: nowrap;
}
.status__dot {
  display: inline-grid;
  flex: none;
  place-items: center;
  width: 14px;
  height: 14px;
  color: var(--dot);
}
/* Running: a ring with one bright arc that turns. Neutral: a still, hollow ring. */
.status__ring {
  width: 11px;
  height: 11px;
  border: var(--stroke-2) solid var(--dot);
  border-radius: var(--radius-full);
}
.status--running .status__ring {
  border-color: color-mix(in srgb, var(--dot) 30%, transparent);
  border-top-color: var(--dot);
  animation: status-turn 1.1s linear infinite;
}
.status--neutral .status__ring {
  border-width: var(--stroke-1);
  border-style: dashed;
}
@keyframes status-turn {
  to {
    transform: rotate(360deg);
  }
}
.status--ok {
  --dot: var(--wt-ok);
}
.status--danger {
  --dot: var(--wt-danger);
}
.status--warn {
  --dot: var(--wt-warn);
}
.status--attention {
  --dot: var(--wt-attention);
}
.status--running {
  --dot: var(--wt-accent-text);
}
.status--neutral {
  --dot: var(--wt-muted);
}
/* Forced colours: the shapes still tell the kinds apart, drawn in the text colour. */
@media (forced-colors: active) {
  .status__dot {
    color: CanvasText;
  }
  .status__ring,
  .status--running .status__ring {
    forced-color-adjust: none;
    border-color: CanvasText;
  }
}
</style>
