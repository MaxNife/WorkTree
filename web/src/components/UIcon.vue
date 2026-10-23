<script setup lang="ts">
import { computed } from 'vue'
import { ICONS, type IconName } from '@/icons/paths'

const props = withDefaults(defineProps<{ name: IconName; size?: number; label?: string }>(), { size: 16 })
// Fluent System Icons (20px grid). Decorative (aria-hidden) unless a label is given.
const markup = computed(() => ICONS[props.name])
</script>

<template>
  <svg
    class="u-icon"
    :width="size"
    :height="size"
    viewBox="0 0 20 20"
    fill="currentColor"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
    focusable="false"
    v-html="markup"
  />
</template>

<style scoped>
.u-icon {
  flex: none;
  vertical-align: middle;
}
</style>
