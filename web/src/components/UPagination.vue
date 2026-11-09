<script setup lang="ts">
// Offset paging for lists: the visible range plus previous and next. Hidden when one page holds it all.
import { computed } from 'vue'
import { formatCount } from '@/format'
import UButton from './UButton.vue'

const offset = defineModel<number>('offset', { default: 0 })
const props = defineProps<{ total: number; limit: number }>()

const first = computed(() => offset.value + 1)
const last = computed(() => Math.min(offset.value + props.limit, props.total))
const atStart = computed(() => offset.value <= 0)
const atEnd = computed(() => offset.value + props.limit >= props.total)

function previous(): void {
  if (!atStart.value) offset.value = Math.max(offset.value - props.limit, 0)
}

function next(): void {
  if (!atEnd.value) offset.value += props.limit
}
</script>

<template>
  <nav v-if="total > limit" class="pagination" aria-label="Pagination">
    <span class="pagination__range">{{ formatCount(first) }}-{{ formatCount(last) }} of {{ formatCount(total) }}</span>
    <UButton appearance="subtle" icon="chevron-left" label="Previous page" :disabled="atStart" @click="previous" />
    <UButton appearance="subtle" icon="chevron-right" label="Next page" :disabled="atEnd" @click="next" />
  </nav>
</template>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-8);
}
.pagination__range {
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
  font-variant-numeric: tabular-nums;
}
.pagination :deep(.u-button) {
  border-color: var(--uaf-border-strong);
  background: var(--uaf-surface);
}
</style>
