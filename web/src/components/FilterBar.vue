<script setup lang="ts">
// The row above a list: optional search, filter controls in the default slot, and "Clear filters".
import { onBeforeUnmount, ref, watch } from 'vue'
import UButton from './UButton.vue'
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
    <UTextInput
      v-if="searchLabel"
      class="filter-bar__search"
      type="search"
      :label="searchLabel"
      :model-value="draft"
      @update:model-value="onSearchInput"
    />
    <slot />
    <UButton v-if="active" appearance="subtle" @click="onClear">Clear filters</UButton>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--uaf-gap);
}
.filter-bar__search {
  margin-right: var(--spacingHorizontalS);
}
</style>
