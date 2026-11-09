<script setup lang="ts">
// A status dot plus its word (GitHub Actions / Temporal style): no pill, border or tinted fill.
// The text is always shown, so colour is never the only signal; neutral states use a hollow dot.
import { computed } from 'vue'
import { statusStyle } from '@/status'

const props = defineProps<{ status: string; label?: string }>()
const style = computed(() => statusStyle(props.status))
const text = computed(() => props.label ?? style.value.label)
</script>

<template>
  <span class="status" :class="`status--${style.kind}`" :data-status="status">
    <span class="status__dot" aria-hidden="true" />
    <span>{{ text }}</span>
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
  flex: none;
  width: var(--uaf-dot-size);
  height: var(--uaf-dot-size);
  border-radius: var(--radius-full);
  background: var(--dot);
  border: var(--stroke-1) solid var(--dot);
}
.status--ok {
  --dot: var(--uaf-ok);
}
.status--danger {
  --dot: var(--uaf-danger);
}
.status--warn {
  --dot: var(--uaf-warn);
}
.status--attention {
  --dot: var(--uaf-attention);
}
.status--running {
  --dot: var(--uaf-accent-text);
}
.status--neutral {
  --dot: var(--uaf-text-muted);
}
.status--neutral .status__dot {
  background: transparent;
}
/* Forced colours drop backgrounds, which would leave every dot hollow. */
@media (forced-colors: active) {
  .status__dot {
    forced-color-adjust: none;
    background: CanvasText;
    border-color: CanvasText;
  }
  .status--neutral .status__dot {
    background: transparent;
  }
}
</style>
