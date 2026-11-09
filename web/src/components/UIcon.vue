<script setup lang="ts">
import { computed } from 'vue'
import { ICONS, ICONS_FILL, type IconName } from '@/icons/paths'

const props = withDefaults(
  defineProps<{ name: IconName; size?: number; label?: string; weight?: 'regular' | 'fill' }>(),
  { size: 16, weight: 'regular' },
)
// Phosphor Icons (256px grid). Regular in the interface; fill where a glyph sits on a coloured shape.
// Decorative (aria-hidden) unless a label is given.
const markup = computed(() => (props.weight === 'fill' ? ICONS_FILL : ICONS)[props.name])
</script>

<template>
  <svg
    class="u-icon"
    :width="size"
    :height="size"
    viewBox="0 0 256 256"
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
