<script setup lang="ts">
// Thin wrapper over <fluent-textarea> with v-model support. The label goes in Fluent's own label slot:
// that is the only one tied to the <textarea> inside its shadow root.
import { computed } from 'vue'

const model = defineModel<string>({ default: '' })
const props = withDefaults(
  defineProps<{
    label: string
    placeholder?: string
    rows?: number
    disabled?: boolean
    required?: boolean
  }>(),
  { rows: 3 },
)

// Fluent replaces `value` with its default-slot text once connected, so the first value goes there.
const initialValue = model.value

// Fluent has no `rows` attribute: its height comes from these host variables.
const size = computed(() => ({
  '--min-block-size': `calc(${props.rows} * var(--line-height) + 2 * var(--padding-block))`,
}))

function onInput(event: Event): void {
  model.value = (event.target as HTMLTextAreaElement).value
}
</script>

<template>
  <fluent-textarea
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
</template>

<style scoped>
.u-field__label {
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
</style>
