<script setup lang="ts">
// A step on the Studio canvas and in replay: the "Rings and Bloom" node (docs/design-language.md).
// A tree cross-section in the colour of the activity family, the label underneath, run state on the
// outer ring (an arc that fills) and as a dot plus word, and the done and failed ports on the right
// edge. Wiring to Vue Flow handles is CP-31.
import { computed } from 'vue'
import type { IconName } from '@/icons/paths'
import { formatDuration, statusStyle } from '@/status'
import { FAMILIES, type Family } from '@/theme/families'
import StatusBadge from './StatusBadge.vue'
import UIcon from './UIcon.vue'

const props = withDefaults(
  defineProps<{
    title: string
    activity: string
    family?: Family
    icon?: IconName
    status?: string
    durationMs?: number | null
    selected?: boolean
  }>(),
  { family: 'logic' },
)

const look = computed(() => FAMILIES[props.family])
// How far the outer ring is drawn, out of 100.
const progress = computed(() => {
  const kind = props.status ? statusStyle(props.status).kind : undefined
  if (props.status === 'done' || props.status === 'failed') return 100
  if (kind === 'running') return 64
  if (kind === 'warn' || kind === 'attention') return 26
  return 0
})
const arcClass = computed(() => (props.status ? `node__arc--${statusStyle(props.status).kind}` : ''))
</script>

<template>
  <article
    class="node"
    :class="{ 'node--selected': selected }"
    :aria-label="`${title}, ${activity}`"
    :style="{ '--node-color': look.color, '--node-ink': look.ink }"
  >
    <div class="node__glyph">
      <svg class="node__rings" viewBox="0 0 96 96" aria-hidden="true">
        <circle class="node__ring node__ring--outer" cx="48" cy="48" r="46" />
        <ellipse class="node__ring node__ring--mid" cx="47.4" cy="48.6" rx="41" ry="40" />
        <ellipse class="node__ring node__ring--inner" cx="48.4" cy="47.6" rx="36" ry="35.2" />
        <ellipse class="node__core" cx="48" cy="48" rx="30.5" ry="29.6" />
        <circle
          v-if="progress"
          class="node__arc"
          :class="arcClass"
          cx="48"
          cy="48"
          r="46"
          pathLength="100"
          :stroke-dasharray="`${progress} ${100 - progress}`"
        />
      </svg>
      <UIcon class="node__icon" :name="icon ?? look.icon" weight="fill" :size="30" />
      <ul class="node__ports" aria-label="Output ports">
        <li class="node__port node__port--done" title="done"><span class="node__port-name">done</span></li>
        <li class="node__port node__port--failed" title="failed"><span class="node__port-name">failed</span></li>
      </ul>
    </div>
    <strong class="node__title">{{ title }}</strong>
    <span class="node__activity">{{ activity }}</span>
    <span v-if="status" class="node__run">
      <StatusBadge :status="status" />
      <span v-if="durationMs != null" class="node__time">{{ formatDuration(durationMs) }}</span>
    </span>
  </article>
</template>

<style scoped>
.node {
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  width: 160px;
  text-align: center;
}
.node__glyph {
  position: relative;
  width: 96px;
  height: 96px;
  margin-bottom: var(--space-4);
}
.node__rings {
  width: 96px;
  height: 96px;
  overflow: visible;
  filter: drop-shadow(0 6px 10px rgb(61 50 35 / 0.14));
}
.node__ring {
  fill: none;
  stroke: var(--node-color);
  stroke-width: 1;
}
.node__ring--outer {
  fill: var(--uaf-surface);
  stroke-opacity: 0.35;
}
.node__ring--mid {
  opacity: 0.75;
}
.node__ring--inner {
  opacity: 0.5;
}
.node__core {
  fill: var(--node-color);
}
.node__arc {
  fill: none;
  stroke: var(--uaf-text-muted);
  stroke-width: 3.5;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 48px 48px;
}
.node__arc--ok {
  stroke: var(--uaf-ok);
}
.node__arc--danger {
  stroke: var(--uaf-danger);
  stroke-dasharray: 12 4;
}
.node__arc--running {
  stroke: var(--uaf-accent-text);
}
.node__arc--warn {
  stroke: var(--uaf-warn);
}
.node__arc--attention {
  stroke: var(--uaf-attention);
}
.node__icon {
  position: absolute;
  left: 33px;
  top: 33px;
  color: var(--node-ink);
}
.node--selected .node__rings {
  border-radius: 50%;
  outline: var(--stroke-2) solid var(--uaf-accent-text);
  outline-offset: 3px;
}
.node__ports {
  position: absolute;
  right: -7px;
  top: 30px;
  display: grid;
  gap: var(--space-12);
  margin: 0;
  padding: 0;
  list-style: none;
}
.node__port {
  width: 12px;
  height: 12px;
  border: var(--stroke-2) solid var(--uaf-surface);
  border-radius: 50%;
  background: var(--uaf-ok);
}
.node__port--failed {
  background: var(--uaf-danger);
}
.node__port-name {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.node__title,
.node__activity {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node__title {
  font-size: var(--font-size-14);
  font-weight: var(--weight-semibold);
}
.node__activity {
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
}
.node__run {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
  font-size: var(--font-size-12);
}
.node__time {
  color: var(--uaf-text-muted);
  font-variant-numeric: tabular-nums;
}
</style>
