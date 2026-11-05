<script setup lang="ts">
// Thin wrapper over <fluent-dropdown> with v-model support. The selection is bound on the options:
// the dropdown's own `value` setter throws until its listbox has been slotted.
import { onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import FieldMessages from './FieldMessages.vue'
import { useFieldMessages } from './field'

const model = defineModel<string>({ default: '' })
const props = defineProps<{
  label: string
  options: { value: string; label: string }[]
  placeholder?: string
  disabled?: boolean
  /** Help text under the field. */
  description?: string
  /** What is wrong with the value. The field is invalid while this is set. */
  error?: string
}>()

const { fieldId, describedBy } = useFieldMessages(props)
const labelId = useId()
const dropdown = ref<HTMLElement & { open?: boolean }>()
let observer: MutationObserver | undefined

// Fluent renders its combobox button after mount and gives it no label. A wrapping <label> is not an
// option here: a click on an option would be re-dispatched to the dropdown and reopen it.
function nameControl(): void {
  const control = dropdown.value?.querySelector('[role="combobox"]')
  if (!control) return
  control.setAttribute('aria-labelledby', labelId)
  setOrRemove(control, 'aria-describedby', describedBy.value)
  setOrRemove(control, 'aria-invalid', props.error ? 'true' : undefined)
}

function setOrRemove(element: Element, name: string, value: string | undefined): void {
  if (value) element.setAttribute(name, value)
  else element.removeAttribute(name)
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
watch(() => [describedBy.value, props.error], nameControl, { flush: 'post' })
</script>

<template>
  <div class="u-field" :class="{ 'u-field--invalid': error, 'u-field--disabled': disabled }">
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
    <FieldMessages :field-id="fieldId" :description="description" :error="error" />
  </div>
</template>

<style scoped>
.u-field {
  display: grid;
  gap: var(--spacingVerticalXXS);
  min-width: 0;
}
.u-field__label {
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
  line-height: var(--lineHeightBase200);
  overflow-wrap: anywhere;
  /* With the grid gap, the 20px Fluent gives the label of a text input: the controls line up in a row. */
  margin-bottom: var(--spacingVerticalXXS);
}
.u-field--disabled .u-field__label {
  color: var(--uaf-text-disabled);
}
/* Fluent sets its border colour inside the shadow root, so the ring goes on the host. */
.u-field--invalid fluent-dropdown {
  border-radius: var(--uaf-radius);
  outline: var(--strokeWidthThin) solid var(--uaf-danger);
  outline-offset: calc(-1 * var(--strokeWidthThin));
}
fluent-listbox {
  border: var(--strokeWidthThin) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
  box-shadow: none;
}
</style>
