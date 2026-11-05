<script setup lang="ts">
// Thin wrapper over <fluent-checkbox> with v-model support.
import ToggleControl from './ToggleControl.vue'

const model = defineModel<boolean>({ default: false })
defineProps<{ label: string; disabled?: boolean; description?: string; error?: string }>()
</script>

<template>
  <ToggleControl
    v-model="model"
    control="fluent-checkbox"
    :label="label"
    :disabled="disabled"
    :description="description"
    :error="error"
  />
</template>
