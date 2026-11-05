<script setup lang="ts">
// Thin wrapper over <fluent-text-input> with v-model support. The label goes in Fluent's default
// slot: that is the only one tied to the <input> inside its shadow root.
import { onMounted, ref, watch } from 'vue'
import FieldMessages from './FieldMessages.vue'
import { useFieldMessages } from './field'

const model = defineModel<string>({ default: '' })
const props = defineProps<{
  label: string
  placeholder?: string
  disabled?: boolean
  readonly?: boolean
  required?: boolean
  type?: 'text' | 'password' | 'search' | 'email' | 'url'
  /** Autofill hint, for example "username" or "current-password" (WCAG 1.3.5). */
  autocomplete?: string
  /** Help text under the field. */
  description?: string
  /** What is wrong with the value. The field is invalid while this is set. */
  error?: string
}>()

const { fieldId } = useFieldMessages(props)
const field = ref<HTMLElement & { control?: HTMLInputElement }>()

function setOrRemove(element: HTMLElement, name: string, value: string): void {
  if (value) element.setAttribute(name, value)
  else element.removeAttribute(name)
}

// An id cannot reach into a shadow root, so the text is set on the <input> Fluent exposes.
function describeControl(): void {
  const control = field.value?.control
  if (!control) return
  setOrRemove(control, 'aria-description', [props.error, props.description].filter(Boolean).join(' '))
  setOrRemove(control, 'aria-invalid', props.error ? 'true' : '')
}

function onInput(event: Event): void {
  model.value = (event.target as HTMLInputElement).value
}

onMounted(describeControl)
watch(() => [props.error, props.description], describeControl, { flush: 'post' })
</script>

<template>
  <div class="u-field" :class="{ 'u-field--invalid': error, 'u-field--disabled': disabled }">
    <fluent-text-input
      ref="field"
      :value="model"
      :placeholder="placeholder"
      :disabled="disabled || undefined"
      :readonly="readonly || undefined"
      :required="required || undefined"
      :type="type ?? 'text'"
      :autocomplete="autocomplete"
      @input="onInput"
    >
      <span class="u-field__label">
        {{ label }}<span v-if="required" class="u-field__required" aria-hidden="true"> *</span>
      </span>
    </fluent-text-input>
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
}
.u-field__required {
  color: var(--uaf-danger);
}
.u-field--disabled .u-field__label {
  color: var(--uaf-text-disabled);
}
fluent-text-input::part(root) {
  height: var(--uaf-control-height);
}
.u-field--invalid fluent-text-input::part(root) {
  border-color: var(--uaf-danger);
}
</style>
