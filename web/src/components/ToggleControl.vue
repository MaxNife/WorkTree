<script setup lang="ts">
// The shared body of UCheckbox and USwitch: a native checkbox inside its label, drawn by us. A switch
// is the same input with role="switch", so screen readers announce on and off.
import UIcon from './UIcon.vue'
import FieldMessages from './FieldMessages.vue'
import { useFieldMessages } from './field'

const model = defineModel<boolean>({ default: false })
const props = defineProps<{
  control: 'checkbox' | 'switch'
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
  <div class="u-toggle" :class="[`u-toggle--${control}`, { 'u-toggle--disabled': disabled }]">
    <label class="u-toggle__row">
      <span class="u-toggle__box">
        <input
          class="u-toggle__input"
          type="checkbox"
          :role="control === 'switch' ? 'switch' : undefined"
          :checked="model"
          :disabled="disabled"
          :aria-describedby="describedBy"
          :aria-invalid="error ? 'true' : undefined"
          @change="onChange"
        />
        <UIcon v-if="control === 'checkbox'" class="u-toggle__tick" name="check" :size="12" weight="fill" />
        <span v-else class="u-toggle__thumb" />
      </span>
      <span class="u-toggle__label">{{ label }}</span>
    </label>
    <FieldMessages :field-id="fieldId" :description="description" :error="error" />
  </div>
</template>

<style scoped>
.u-toggle {
  display: inline-grid;
  gap: var(--space-2);
  min-width: 0;
}
.u-toggle__row {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
  min-height: var(--uaf-control-height);
  cursor: pointer;
}
.u-toggle__box {
  position: relative;
  display: inline-grid;
  place-items: center;
  flex: none;
}
.u-toggle__input {
  appearance: none;
  margin: 0;
  border: var(--stroke-1) solid var(--uaf-border-control);
  background: var(--uaf-surface);
  cursor: inherit;
  transition:
    background-color var(--duration-fast) var(--ease-standard),
    border-color var(--duration-fast) var(--ease-standard);
}
.u-toggle--checkbox .u-toggle__input {
  width: 18px;
  height: 18px;
  border-radius: 5px;
}
.u-toggle--switch .u-toggle__input {
  width: 36px;
  height: 20px;
  border-radius: var(--radius-full);
}
.u-toggle__input:checked {
  border-color: var(--uaf-control);
  background: var(--uaf-control);
}
.u-toggle__input:checked:hover {
  border-color: var(--uaf-control-hover);
  background: var(--uaf-control-hover);
}
.u-toggle__input:focus-visible {
  outline: var(--uaf-focus-width) solid var(--uaf-focus);
  outline-offset: var(--uaf-focus-width);
}
.u-toggle__input[aria-invalid='true'] {
  border-color: var(--uaf-danger);
}
.u-toggle__tick {
  position: absolute;
  color: var(--uaf-surface);
  opacity: 0;
  pointer-events: none;
}
.u-toggle__input:checked + .u-toggle__tick {
  opacity: 1;
}
.u-toggle__thumb {
  position: absolute;
  left: 4px;
  top: 4px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--uaf-border-control);
  pointer-events: none;
  transition: transform var(--duration-normal) var(--ease-standard);
}
.u-toggle__input:checked + .u-toggle__thumb {
  background: var(--uaf-surface);
  transform: translateX(16px);
}
.u-toggle__label {
  overflow-wrap: anywhere;
}
/* Windows High Contrast replaces backgrounds, so state is drawn in system colours instead. */
@media (forced-colors: active) {
  .u-toggle__input {
    forced-color-adjust: none;
    border-color: ButtonText;
    background: Canvas;
  }
  .u-toggle__input:checked,
  .u-toggle__input:checked:hover {
    border-color: Highlight;
    background: Highlight;
  }
  .u-toggle__tick {
    color: HighlightText;
  }
  .u-toggle__thumb {
    forced-color-adjust: none;
    background: ButtonText;
  }
  .u-toggle__input:checked + .u-toggle__thumb {
    background: HighlightText;
  }
  .u-toggle--disabled .u-toggle__input {
    border-color: GrayText;
  }
}
.u-toggle--disabled .u-toggle__row {
  cursor: not-allowed;
}
.u-toggle--disabled .u-toggle__input {
  border-color: var(--uaf-border);
  background: var(--uaf-surface-disabled);
}
.u-toggle--disabled .u-toggle__label {
  color: var(--uaf-text-disabled);
}
</style>
