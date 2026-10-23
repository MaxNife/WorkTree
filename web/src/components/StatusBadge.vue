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
  gap: var(--spacingHorizontalS);
  white-space: nowrap;
}
.status__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--dot);
  border: var(--strokeWidthThin) solid var(--dot);
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
  --dot: var(--uaf-accent);
}
.status--neutral {
  --dot: var(--uaf-text-muted);
}
.status--neutral .status__dot {
  background: transparent;
}
</style>
