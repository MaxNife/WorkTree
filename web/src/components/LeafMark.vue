<script setup lang="ts">
// The leaf (docs/04 3.3): WorkTree's own corner shape, used as the marker for each area in the
// sidebar and beside a task or list item. Decorative: the label beside it carries the meaning.
import { computed } from 'vue'
import { colourVars, type AreaColour } from '@/theme/areas'

const props = withDefaults(defineProps<{ colour: AreaColour; size?: number }>(), { size: 12 })
const fill = computed(() => colourVars(props.colour).strong)
</script>

<template>
  <span class="leaf" aria-hidden="true" :style="{ '--leaf-fill': fill, width: `${size}px`, height: `${size}px` }" />
</template>

<style scoped>
.leaf {
  display: inline-block;
  flex: none;
  border-radius: var(--wt-leaf);
  background: var(--leaf-fill);
}
@media (forced-colors: active) {
  .leaf {
    forced-color-adjust: none;
    background: CanvasText;
  }
}
</style>
