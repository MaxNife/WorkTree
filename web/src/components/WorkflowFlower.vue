<script setup lang="ts">
// A workflow's flower: its colour and petal count around a Night soil centre (docs/04 3.1). It is
// derived from the workflow id until the backend stores a choice; `flower` and `petals` override it.
// Decorative: the workflow's name always sits beside it.
import { computed } from 'vue'
import { clampPetals, flower as drawFlower, flowerFor } from '@/plants'
import type { FlowerName } from '@/theme/tokens'

const props = withDefaults(defineProps<{ id?: string; flower?: FlowerName; petals?: number; size?: number }>(), {
  id: '',
  size: 20,
})

const identity = computed(() => flowerFor(props.id))
const colour = computed(() => props.flower ?? identity.value.flower)
const count = computed(() => clampPetals(props.petals ?? identity.value.petals))
// More petals need narrower ones, so the flower keeps the same weight from five to nine.
const drawing = computed(() => drawFlower({ petals: count.value, length: 10.5, width: 4.6 * (5 / count.value) + 1.4 }))
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
    <g :fill="`var(--wt-${colour})`">
      <path v-for="angle in drawing.angles" :key="angle" :transform="`rotate(${angle})`" :d="drawing.petal" />
    </g>
    <circle class="workflow-flower__centre" r="3" />
    <circle class="workflow-flower__core" r="1.1" />
  </svg>
</template>

<style scoped>
.workflow-flower {
  flex: none;
}
.workflow-flower__centre {
  fill: var(--wt-ink);
}
.workflow-flower__core {
  fill: var(--wt-surface);
}
@media (forced-colors: active) {
  .workflow-flower {
    forced-color-adjust: none;
  }
  .workflow-flower g {
    fill: CanvasText;
  }
  .workflow-flower__centre {
    fill: Canvas;
    stroke: CanvasText;
  }
}
</style>
