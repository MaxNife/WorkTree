<script setup lang="ts">
// A tab strip with a roving tabindex; arrow keys, Home and End select as they move. The caller renders
// the panel for the selected tab.
import { computed, ref } from 'vue'
import { formatCount } from '@/format'

const model = defineModel<string>({ default: '' })
const props = defineProps<{ tabs: { id: string; label: string; count?: number }[]; label: string }>()

const list = ref<HTMLElement>()
const tabStop = computed(() => (props.tabs.some((tab) => tab.id === model.value) ? model.value : props.tabs[0]?.id))

function targetIndex(key: string, index: number): number | undefined {
  const count = props.tabs.length
  if (key === 'ArrowRight') return (index + 1) % count
  if (key === 'ArrowLeft') return (index - 1 + count) % count
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  return undefined
}

function onKeydown(event: KeyboardEvent, index: number): void {
  const target = targetIndex(event.key, index)
  if (target === undefined) return
  event.preventDefault()
  model.value = props.tabs[target]?.id ?? model.value
  list.value?.querySelectorAll<HTMLElement>('[role="tab"]')[target]?.focus()
}
</script>

<template>
  <div ref="list" class="tabs" role="tablist" :aria-label="label">
    <button
      v-for="(tab, index) in tabs"
      :key="tab.id"
      class="tabs__tab"
      :class="{ 'tabs__tab--selected': tab.id === model }"
      type="button"
      role="tab"
      :aria-selected="tab.id === model"
      :tabindex="tab.id === tabStop ? 0 : -1"
      @click="model = tab.id"
      @keydown="onKeydown($event, index)"
    >
      {{ tab.label }}
      <span v-if="tab.count !== undefined" class="tabs__count">{{ formatCount(tab.count) }}</span>
    </button>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  border-bottom: var(--stroke-1) solid var(--wt-line);
}
.tabs__tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: calc(var(--stroke-1) * -1);
  padding: var(--space-8) var(--space-10);
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: var(--wt-radius) var(--wt-radius) 0 0;
  background: none;
  color: var(--wt-muted);
  font: inherit;
  cursor: pointer;
  transition:
    color var(--duration-fast) var(--ease-standard),
    background-color var(--duration-fast) var(--ease-standard);
}
.tabs__tab:hover {
  background: var(--wt-surface-hover);
  color: var(--wt-ink);
}
.tabs__tab:focus-visible {
  outline-offset: calc(-1 * var(--wt-focus-width));
}
.tabs__tab--selected {
  border-bottom-color: var(--wt-accent-text);
  color: var(--wt-ink);
  font-weight: var(--weight-semibold);
}
.tabs__count {
  min-width: 20px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-full);
  background: var(--wt-sunken);
  color: var(--wt-muted);
  font-size: var(--font-size-12);
  font-weight: var(--weight-semibold);
  line-height: var(--line-height-20);
  font-variant-numeric: tabular-nums;
  text-align: center;
}
.tabs__tab--selected .tabs__count {
  background: var(--wt-accent-tint);
  color: var(--wt-accent-text);
}
</style>
