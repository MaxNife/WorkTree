<script setup lang="ts">
// A labelled native <select> with v-model support. Native on purpose: the browser gives it keyboard
// use, type-ahead and screen-reader support that a drawn list box would have to rebuild.
import { computed } from 'vue'
import UIcon from './UIcon.vue'
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
const hasEmptyOption = computed(() => props.options.some((option) => option.value === ''))

function onChange(event: Event): void {
  model.value = (event.target as HTMLSelectElement).value
}
</script>

<template>
  <div class="u-field" :class="{ 'u-field--invalid': error, 'u-field--disabled': disabled }">
    <label :for="fieldId" class="u-field__label">{{ label }}</label>
    <span class="u-select">
      <select
        :id="fieldId"
        class="u-control u-select__control"
        :value="model"
        :disabled="disabled"
        :aria-describedby="describedBy"
        :aria-invalid="error ? 'true' : undefined"
        @change="onChange"
      >
        <option v-if="placeholder" value="" disabled :selected="!model">{{ placeholder }}</option>
        <!-- Without this, the browser would show the first option as chosen while nothing is, and
             picking it would fire no change. -->
        <option v-else-if="!model && !hasEmptyOption" value="" disabled hidden selected />

        <option v-for="option in options" :key="option.value" :value="option.value" :selected="option.value === model">
          {{ option.label }}
        </option>
      </select>
      <UIcon class="u-select__caret" name="chevron-down" :size="14" />
    </span>
    <FieldMessages :field-id="fieldId" :description="description" :error="error" />
  </div>
</template>

<style scoped>
.u-select {
  position: relative;
  display: grid;
  min-width: 0;
}
.u-select__control {
  appearance: none;
  padding-right: var(--space-32);
  cursor: pointer;
}
.u-select__caret {
  position: absolute;
  right: var(--space-10);
  top: 50%;
  transform: translateY(-50%);
  color: var(--wt-muted);
  pointer-events: none;
}
</style>
