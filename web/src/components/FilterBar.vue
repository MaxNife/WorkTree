<script setup lang="ts">
// The row above a list: optional search, filter controls in the default slot, and "Clear filters".
import { onBeforeUnmount, ref, watch } from 'vue'
import UButton from './UButton.vue'
import UIcon from './UIcon.vue'
import UTextInput from './UTextInput.vue'

const DEBOUNCE_MS = 250

const search = defineModel<string>('search', { default: '' })
defineProps<{ searchLabel?: string; active?: boolean }>()
const emit = defineEmits<{ clear: [] }>()

const draft = ref(search.value)
let timer: ReturnType<typeof setTimeout> | undefined

function onSearchInput(value: string): void {
  draft.value = value
  clearTimeout(timer)
  timer = setTimeout(() => {
    search.value = value
  }, DEBOUNCE_MS)
}

function onClear(): void {
  clearTimeout(timer)
  draft.value = ''
  search.value = ''
  emit('clear')
}

// A change from outside wins over anything still waiting on the debounce.
watch(search, (value) => {
  clearTimeout(timer)
  draft.value = value
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="filter-bar">
    <div v-if="searchLabel" class="filter-bar__search">
      <UTextInput type="search" :label="searchLabel" :model-value="draft" @update:model-value="onSearchInput" />
      <UIcon class="filter-bar__search-icon" name="search" :size="16" />
    </div>
    <slot />
    <UButton v-if="active" class="filter-bar__clear" appearance="subtle" icon="filter-clear" @click="onClear">Clear filters</UButton>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-8) var(--space-12);
  padding: var(--space-10) var(--space-12);
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius-container);
  background: var(--wt-sunken);
}
.filter-bar__search {
  position: relative;
  flex: 1 1 220px;
  max-width: 320px;
}
.filter-bar__search :deep(input) {
  padding-left: var(--space-32);
}
.filter-bar__search-icon {
  position: absolute;
  left: var(--space-10);
  bottom: calc((var(--wt-control-height) - 16px) / 2);
  color: var(--wt-muted);
  pointer-events: none;
}
.filter-bar__clear {
  margin-left: auto;
}
</style>
