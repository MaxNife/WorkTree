<script setup lang="ts">
// Thin wrapper over <fluent-checkbox> with v-model support.
const model = defineModel<boolean>({ default: false })
defineProps<{ label: string; disabled?: boolean }>()

// Fluent's control has no label slot, so the visible text is our own span inside a label.
function onChange(event: Event): void {
  model.value = (event.target as HTMLInputElement).checked
}
</script>

<template>
  <label class="u-toggle">
    <fluent-checkbox :checked="model || undefined" :disabled="disabled || undefined" :aria-label="label" @change="onChange" />
    <span>{{ label }}</span>
  </label>
</template>

<style scoped>
.u-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  cursor: pointer;
}
</style>
