<script setup lang="ts">
// A labelled native <textarea> with v-model support. Help and error text are tied to it by id.
import FieldMessages from './FieldMessages.vue'
import { useFieldMessages } from './field'

const model = defineModel<string>({ default: '' })
const props = withDefaults(
  defineProps<{
    label: string
    placeholder?: string
    rows?: number
    disabled?: boolean
    required?: boolean
    /** Help text under the field. */
    description?: string
    /** What is wrong with the value. The field is invalid while this is set. */
    error?: string
  }>(),
  { rows: 3 },
)

const { fieldId, describedBy } = useFieldMessages(props)

function onInput(event: Event): void {
  model.value = (event.target as HTMLTextAreaElement).value
}
</script>

<template>
  <div class="u-field" :class="{ 'u-field--invalid': error, 'u-field--disabled': disabled }">
    <label :for="fieldId" class="u-field__label">
      {{ label }}<span v-if="required" class="u-field__required" aria-hidden="true"> *</span>
    </label>
    <textarea
      :id="fieldId"
      class="u-control u-textarea"
      :value="model"
      :rows="rows"
      :placeholder="placeholder"
      :disabled="disabled"
      :required="required"
      :aria-describedby="describedBy"
      :aria-invalid="error ? 'true' : undefined"
      @input="onInput"
    />
    <FieldMessages :field-id="fieldId" :description="description" :error="error" />
  </div>
</template>

<style scoped>
.u-textarea {
  resize: vertical;
  padding-block: var(--space-6);
}
</style>
