<script setup lang="ts">
// A status pill: a soft tint of the status flower, a mark and the word in its deep value. Each kind has
// its own mark as well as its own colour (a tick, a cross, a clock, an alert, an open ring, a dashed
// ring), and the word is always shown, so colour is never the only signal. Nothing here moves: in the
// garden only the petals of a running step fill (docs/04 3.4).
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
  /* A pill keeps its own width when it is a grid or flex item. */
  justify-self: start;
  align-self: center;
  gap: var(--space-4);
  min-height: 20px;
  padding: 0 var(--space-8) 0 var(--space-4);
  border-radius: var(--radius-full);
  background: var(--tint);
  color: var(--word);
  font-size: var(--font-size-12);
  font-weight: var(--weight-semibold);
  line-height: var(--line-height-16);
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
/* Running: a ring with one solid arc. Neutral: a still, dashed ring. */
.status__ring {
  width: 10px;
  height: 10px;
  border: var(--stroke-2) solid var(--dot);
  border-radius: var(--radius-full);
}
.status--running .status__ring {
  border-color: color-mix(in srgb, var(--dot) 35%, transparent);
  border-top-color: var(--dot);
  border-right-color: var(--dot);
  transform: rotate(-45deg);
}
.status--neutral .status__ring {
  border-width: var(--stroke-1);
  border-style: dashed;
}
.status--ok {
  --tint: var(--wt-ok-bg);
  --word: var(--wt-ok);
  --dot: var(--wt-ok);
}
.status--danger {
  --tint: var(--wt-danger-bg);
  --word: var(--wt-danger);
  --dot: var(--wt-danger);
}
.status--warn {
  --tint: var(--wt-warn-bg);
  --word: var(--wt-warn);
  --dot: var(--wt-warn);
}
.status--attention {
  --tint: var(--wt-attention-bg);
  --word: var(--wt-attention);
  --dot: var(--wt-attention);
}
.status--running {
  --tint: var(--wt-running-bg);
  --word: var(--wt-running);
  --dot: var(--wt-running);
}
.status--neutral {
  --tint: var(--wt-sunken);
  --word: var(--wt-muted);
  --dot: var(--wt-muted);
}
/* Forced colours drop the tint, so the pill gets an edge; the marks still tell the kinds apart. */
@media (forced-colors: active) {
  .status {
    border: var(--stroke-1) solid CanvasText;
  }
  .status__dot {
    color: CanvasText;
  }
  .status__ring,
  .status--running .status__ring {
    forced-color-adjust: none;
    border-color: CanvasText;
  }
  .status--running .status__ring {
    border-bottom-color: transparent;
    border-left-color: transparent;
  }
}
</style>
