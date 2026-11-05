<script setup lang="ts">
// Thin wrapper over <fluent-textarea> with v-model support. The label goes in Fluent's own label slot:
// that is the only one tied to the <textarea> inside its shadow root.
import { computed, onMounted, ref, watch } from 'vue'
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

const { fieldId } = useFieldMessages(props)
const field = ref<HTMLElement & { controlEl?: HTMLTextAreaElement }>()

// Fluent replaces `value` with its default-slot text once connected, so the first value goes there.
const initialValue = model.value

// Fluent has no `rows` attribute: its height comes from these host variables.
const size = computed(() => ({
  '--min-block-size': `calc(${props.rows} * var(--line-height) + 2 * var(--padding-block))`,
}))

function setOrRemove(element: HTMLElement, name: string, value: string): void {
  if (value) element.setAttribute(name, value)
  else element.removeAttribute(name)
}

// An id cannot reach into a shadow root, so the text is set on the <textarea> Fluent exposes.
function describeControl(): void {
  const control = field.value?.controlEl
  if (!control) return
  setOrRemove(control, 'aria-description', [props.error, props.description].filter(Boolean).join(' '))
  setOrRemove(control, 'aria-invalid', props.error ? 'true' : '')
}

function onInput(event: Event): void {
  model.value = (event.target as HTMLTextAreaElement).value
}

onMounted(describeControl)
watch(() => [props.error, props.description], describeControl, { flush: 'post' })
</script>

<template>
  <div class="u-field" :class="{ 'u-field--invalid': error, 'u-field--disabled': disabled }">
    <fluent-textarea
      ref="field"
      :block="true"
      :style="size"
      :value="model"
      :placeholder="placeholder"
      :disabled="disabled || undefined"
      :required="required || undefined"
      @input="onInput"
    >
      <!-- eslint-disable-next-line vue/no-deprecated-slot-attribute -- native custom-element slot -->
      <span slot="label" class="u-field__label">{{ label }}</span>
      {{ initialValue }}
    </fluent-textarea>
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
.u-field--disabled .u-field__label {
  color: var(--uaf-text-disabled);
}
.u-field--invalid fluent-textarea::part(root) {
  border-color: var(--uaf-danger);
}
</style>
