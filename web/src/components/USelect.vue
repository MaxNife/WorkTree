<script setup lang="ts">
// Thin wrapper over <fluent-dropdown> with v-model support. The selection is bound on the options:
// the dropdown's own `value` setter throws until its listbox has been slotted.
import { onBeforeUnmount, onMounted, ref, useId } from 'vue'

const model = defineModel<string>({ default: '' })
defineProps<{
  label: string
  options: { value: string; label: string }[]
  placeholder?: string
  disabled?: boolean
}>()

const labelId = useId()
const dropdown = ref<HTMLElement & { open?: boolean }>()
let observer: MutationObserver | undefined

// Fluent renders its combobox button after mount and gives it no label. A wrapping <label> is not an
// option here: a click on an option would be re-dispatched to the dropdown and reopen it.
function nameControl(): void {
  dropdown.value?.querySelector('[role="combobox"]')?.setAttribute('aria-labelledby', labelId)
}

function onChange(event: Event): void {
  model.value = (event.currentTarget as HTMLInputElement).value ?? ''
}

// Escape closes only the open list, not a dialog around it.
function onEscape(event: KeyboardEvent): void {
  if (dropdown.value?.open) event.preventDefault()
}

onMounted(() => {
  if (!dropdown.value) return
  nameControl()
  observer = new MutationObserver(nameControl)
  observer.observe(dropdown.value, { childList: true })
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div class="u-field">
    <span :id="labelId" class="u-field__label">{{ label }}</span>
    <fluent-dropdown
      ref="dropdown"
      :placeholder="placeholder"
      :disabled="disabled || undefined"
      @change="onChange"
      @keydown.esc.capture="onEscape"
    >
      <fluent-listbox>
        <fluent-option
          v-for="option in options"
          :key="option.value"
          :value="option.value"
          :selected="option.value === model || undefined"
        >
          {{ option.label }}
        </fluent-option>
      </fluent-listbox>
    </fluent-dropdown>
  </div>
</template>

<style scoped>
.u-field {
  display: grid;
  gap: var(--spacingVerticalXS);
}
.u-field__label {
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
fluent-listbox {
  border: var(--strokeWidthThin) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
  box-shadow: none;
}
</style>
