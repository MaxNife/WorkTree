<script setup lang="ts">
// A workflow's flower: the solid, scalloped flower of the mockup sheet in its colour, with five to nine
// round petals and a light core (docs/04 3.1). It is derived from the workflow id until the backend
// stores a choice; `flower` and `petals` override it.
// Decorative: the workflow's name always sits beside it.
import { computed } from 'vue'
import { clampPetals, flowerFor, roundFlower } from '@/plants'
import { colourVars } from '@/theme/areas'
import type { FlowerName } from '@/theme/tokens'

const props = withDefaults(defineProps<{ id?: string; flower?: FlowerName; petals?: number; size?: number }>(), {
  id: '',
  size: 20,
})

const identity = computed(() => flowerFor(props.id))
const colour = computed(() => props.flower ?? identity.value.flower)
const count = computed(() => clampPetals(props.petals ?? identity.value.petals))
const drawing = computed(() => roundFlower({ petals: count.value, radius: 11.4 }))
const fill = computed(() => colourVars(colour.value).strong)
</script>

<template>
  <svg
    class="workflow-flower"
    :width="size"
    :height="size"
    viewBox="-12 -12 24 24"
    aria-hidden="true"
    focusable="false"
    :data-flower="colour"
    :data-petals="count"
  >
    <g class="workflow-flower__bloom" :fill="fill">
      <circle v-for="(p, index) in drawing.petals" :key="index" :cx="p.cx" :cy="p.cy" :r="p.r" />
      <circle :r="drawing.body" />
    </g>
    <circle class="workflow-flower__core" :r="drawing.core" />
  </svg>
</template>

<style scoped>
.workflow-flower {
  flex: none;
}
.workflow-flower__core {
  fill: var(--wt-surface);
}
@media (forced-colors: active) {
  .workflow-flower {
    forced-color-adjust: none;
  }
  .workflow-flower__bloom {
    fill: CanvasText;
  }
  .workflow-flower__core {
    fill: Canvas;
  }
}
</style>
