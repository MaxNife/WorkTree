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
  gap: var(--space-16);
  border-bottom: var(--stroke-1) solid var(--uaf-border);
}
.tabs__tab {
  display: inline-flex;
  gap: var(--space-4);
  margin-bottom: calc(var(--stroke-1) * -1);
  padding: var(--space-8) 0;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--uaf-text-muted);
  font: inherit;
  cursor: pointer;
}
.tabs__tab:hover {
  color: var(--uaf-text);
}
.tabs__tab--selected {
  border-bottom-color: var(--uaf-accent-text);
  color: var(--uaf-text);
  font-weight: var(--weight-semibold);
}
.tabs__count {
  color: var(--uaf-text-muted);
  font-weight: normal;
}
</style>
