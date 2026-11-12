<script setup lang="ts">
// The area band (docs/04 5): directly under the top bar on an area's main pages, in the area's soft
// tint. It holds the page title, one sentence of live summary, the page's main action (a `strong`
// button in the `action` slot) and two drawn flowers. Tall on an area's landing page, short elsewhere.
// When the page shows prod, a Night soil "prod" pill sits by the title and a 3 px line runs along the
// bottom; other environments show a quiet outlined pill.
// Given a `workflowId` instead of a colour, the band takes that workflow's colour and shows its flower
// before the title (run detail, docs/04 8.2). The `badges` slot adds pills beside the title.
import { computed } from 'vue'
import { flowerFor } from '@/plants'
import { colourVars, neighbour, type AreaColour } from '@/theme/areas'
import WorkflowFlower from './WorkflowFlower.vue'

const props = withDefaults(
  defineProps<{
    colour?: AreaColour
    workflowId?: string
    title: string
    summary?: string
    size?: 'tall' | 'short'
    environment?: string
  }>(),
  { size: 'short' },
)

const tint = computed<AreaColour>(() => props.colour ?? (props.workflowId ? flowerFor(props.workflowId).flower : 'night-soil'))
const vars = computed(() => {
  const { soft, deep } = colourVars(tint.value)
  return { '--band-fill': soft, '--band-deep': deep }
})
const first = computed(() => (tint.value === 'night-soil' ? 'iris' : tint.value))
const second = computed(() => neighbour(tint.value))
const isProd = computed(() => props.environment?.toLowerCase() === 'prod')
const big = computed(() => (props.size === 'tall' ? 52 : 36))
</script>

<template>
  <header class="band" :class="[`band--${size}`, { 'band--prod': isProd }]" :style="vars" :data-colour="tint">
    <div class="band__text">
      <div class="band__title-row">
        <WorkflowFlower v-if="workflowId" :id="workflowId" :size="size === 'tall' ? 32 : 26" />
        <h1 class="band__title">{{ title }}</h1>
        <span v-if="environment" class="band__env" :class="{ 'band__env--prod': isProd }">{{ environment }}</span>
        <slot name="badges" />
      </div>
      <p v-if="summary || $slots.summary" class="band__summary">
        <slot name="summary">{{ summary }}</slot>
      </p>
    </div>
    <div v-if="$slots.action" class="band__action">
      <slot name="action" />
    </div>
    <div class="band__garden" aria-hidden="true">
      <WorkflowFlower class="band__flower band__flower--small" :flower="second" :petals="5" :size="Math.round(big * 0.6)" />
      <WorkflowFlower v-if="workflowId" :id="workflowId" class="band__flower" :size="big" />
      <WorkflowFlower v-else class="band__flower" :flower="first" :petals="7" :size="big" />
    </div>
  </header>
</template>

<style scoped>
.band {
  display: flex;
  align-items: center;
  gap: var(--space-16);
  min-height: 64px;
  padding: var(--space-12) var(--space-20);
  border-radius: var(--wt-radius-container);
  background: var(--band-fill);
  color: var(--wt-ink);
}
.band--tall {
  min-height: 96px;
  padding: var(--space-16) var(--space-24);
}
.band--prod {
  box-shadow: inset 0 -3px 0 var(--wt-strong);
}
.band__text {
  display: grid;
  flex: 1;
  gap: var(--space-2);
  min-width: 0;
}
.band__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-8);
}
.band__title {
  font-size: var(--font-size-20);
  line-height: var(--line-height-28);
  overflow-wrap: anywhere;
}
.band--tall .band__title {
  font-size: var(--font-size-24);
  line-height: var(--line-height-30);
}
.band__summary {
  margin: 0;
  color: var(--band-deep);
}
.band__env {
  padding: 0 var(--space-8);
  border: var(--stroke-1) solid var(--wt-ink);
  border-radius: var(--radius-full);
  font-size: var(--font-size-11);
  font-weight: var(--weight-semibold);
  line-height: var(--line-height-16);
  letter-spacing: 0.02em;
}
.band__env--prod {
  border-color: var(--wt-strong);
  background: var(--wt-strong);
  color: var(--wt-on-strong);
}
.band__action {
  display: flex;
  flex: none;
  gap: var(--space-8);
}
.band__garden {
  display: flex;
  flex: none;
  align-items: flex-end;
  gap: var(--space-2);
}
.band__flower--small {
  margin-bottom: var(--space-2);
}
@media (max-width: 640px) {
  .band__garden {
    display: none;
  }
}
/* High contrast drops the tints, so the band keeps its shape with an edge. */
:root[data-theme='high-contrast'] .band {
  border: var(--stroke-1) solid var(--wt-line);
}
@media (forced-colors: active) {
  .band {
    border: var(--stroke-1) solid CanvasText;
  }
}
</style>
