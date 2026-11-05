<script setup lang="ts">
// The shared body of UCheckbox and USwitch. Fluent's control has no label slot, so the visible text
// is our own span inside a label. These Fluent controls are themselves the focusable element, so
// aria-describedby reaches them with plain ids.
import FieldMessages from './FieldMessages.vue'
import { useFieldMessages } from './field'

const model = defineModel<boolean>({ default: false })
const props = defineProps<{
  control: 'fluent-checkbox' | 'fluent-switch'
  label: string
  disabled?: boolean
  description?: string
  error?: string
}>()

const { fieldId, describedBy } = useFieldMessages(props)

function onChange(event: Event): void {
  model.value = (event.target as HTMLInputElement).checked
}
</script>

<template>
  <div class="u-toggle" :class="{ 'u-toggle--disabled': disabled }">
    <label class="u-toggle__row">
      <component
        :is="control"
        class="u-toggle__control"
        :checked="model || undefined"
        :disabled="disabled || undefined"
        :aria-describedby="describedBy"
        :aria-invalid="error ? 'true' : undefined"
        @change="onChange"
      />
      <span class="u-toggle__label">{{ label }}</span>
    </label>
    <FieldMessages :field-id="fieldId" :description="description" :error="error" />
  </div>
</template>

<style scoped>
.u-toggle {
  display: inline-grid;
  gap: var(--spacingVerticalXXS);
  min-width: 0;
}
.u-toggle__row {
  display: inline-flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  min-height: var(--uaf-control-height);
  cursor: pointer;
}
.u-toggle__control {
  flex: none;
}
.u-toggle__label {
  overflow-wrap: anywhere;
}
.u-toggle--disabled .u-toggle__row {
  cursor: not-allowed;
}
.u-toggle--disabled .u-toggle__label {
  color: var(--uaf-text-disabled);
}
</style>
