<script setup lang="ts">
// A switch with v-model support: a checkbox announced as a switch.
import ToggleControl from './ToggleControl.vue'

const model = defineModel<boolean>({ default: false })
defineProps<{ label: string; disabled?: boolean; description?: string; error?: string }>()
</script>

<template>
  <ToggleControl
    v-model="model"
    control="switch"
    :label="label"
    :disabled="disabled"
    :description="description"
    :error="error"
  />
</template>
