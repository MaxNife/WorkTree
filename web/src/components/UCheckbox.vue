<script setup lang="ts">
// A checkbox with v-model support.
import ToggleControl from './ToggleControl.vue'

const model = defineModel<boolean>({ default: false })
defineProps<{ label: string; disabled?: boolean; description?: string; error?: string }>()
</script>

<template>
  <ToggleControl
    v-model="model"
    control="checkbox"
    :label="label"
    :disabled="disabled"
    :description="description"
    :error="error"
  />
</template>
