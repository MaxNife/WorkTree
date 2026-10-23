<script setup lang="ts">
// Thin wrapper over <fluent-text-input> with v-model support.
const model = defineModel<string>({ default: '' })
defineProps<{ label: string; placeholder?: string; disabled?: boolean; type?: 'text' | 'password' | 'search' }>()

function onInput(event: Event): void {
  model.value = (event.target as HTMLInputElement).value
}
</script>

<template>
  <label class="u-field">
    <span class="u-field__label">{{ label }}</span>
    <fluent-text-input
      :value="model"
      :placeholder="placeholder"
      :disabled="disabled || undefined"
      :type="type ?? 'text'"
      :aria-label="label"
      @input="onInput"
    />
  </label>
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
</style>
