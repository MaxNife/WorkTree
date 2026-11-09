<script setup lang="ts">
// A labelled native <input> with v-model support. Help and error text are tied to it by id.
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

const { fieldId, describedBy } = useFieldMessages(props)

function onInput(event: Event): void {
  model.value = (event.target as HTMLInputElement).value
}
</script>

<template>
  <div class="u-field" :class="{ 'u-field--invalid': error, 'u-field--disabled': disabled }">
    <label :for="fieldId" class="u-field__label">
      {{ label }}<span v-if="required" class="u-field__required" aria-hidden="true"> *</span>
    </label>
    <input
      :id="fieldId"
      class="u-control"
      :value="model"
      :placeholder="placeholder"
      :disabled="disabled"
      :readonly="readonly"
      :required="required"
      :type="type ?? 'text'"
      :autocomplete="autocomplete"
      :aria-describedby="describedBy"
      :aria-invalid="error ? 'true' : undefined"
      @input="onInput"
    />
    <FieldMessages :field-id="fieldId" :description="description" :error="error" />
  </div>
</template>
