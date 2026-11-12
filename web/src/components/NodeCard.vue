<script setup lang="ts">
// A step on the Studio canvas and in run replay: a solid plant (docs/04 10.3, docs/07 8.2, drawn as on
// the approved mockup sheet). Shape says what the node does, colour which app it belongs to. The
// label and one line of summary sit underneath; run state is drawn on the plant and as a pill.
//
//   pending      a pale outline            running   petals fill clockwise (or to `progress`)
//   done         full colour, opening once when it finishes while on screen
//   failed       wilted, with a hibiscus dot           waiting   a dashed halo
//   selected     a dotted ring             incomplete  outlined (needs setup)   problem  a dot
//
// Halo and ring use the deep value so they reach 3:1 on the ground. Wiring ports to the canvas
// library is part of the canvas kit.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { IconName } from '@/icons/paths'
import { bud, flower, petal, roundFlower, seed } from '@/plants'
import { formatDuration, statusStyle } from '@/status'
import { activityLook, type NodeKind, type NodeLook } from '@/theme/apps'
import { colourVars, type AreaColour } from '@/theme/areas'
import StatusBadge from './StatusBadge.vue'
import UIcon from './UIcon.vue'

const props = withDefaults(
  defineProps<{
    title: string
    activity?: string
    /** Overrides what the activity says: kind, colour, icon or label. */
    look?: Partial<NodeLook>
    summary?: string
    status?: string
    durationMs?: number | null
    /** Share of the work done while running, 0 to 1. Without it the petals fill in a loop. */
    progress?: number
    selected?: boolean
    /** Required setup is missing (no connection, an empty required field). */
    incomplete?: boolean
    /** Validation found something wrong with this node. */
    problem?: boolean
    /** Router only: the colour of the node each route leads to, one petal each. */
    routes?: AreaColour[]
    /** Output ports. Finish and Stop end the run and have none; everything else has done and failed. */
    ports?: string[]
  }>(),
  { activity: '', ports: undefined },
)

// Skills draw with pointed petals (docs/04 15, open item 2, not yet seen by the owner). Set this to
// 'round' to drop the proposal.
const SKILL_PETALS: 'pointed' | 'round' = 'pointed'

const look = computed<NodeLook>(() => ({ ...activityLook(props.activity), ...props.look }))
const kind = computed<NodeKind>(() => look.value.kind)
const vars = computed(() => {
  const { strong, soft, deep } = colourVars(look.value.colour)
  return { '--c-strong': strong, '--c-soft': soft, '--c-deep': deep }
})

type State = 'idle' | 'pending' | 'running' | 'done' | 'failed' | 'waiting'
const state = computed<State>(() => {
  if (!props.status) return 'idle'
  const style = statusStyle(props.status).kind
  if (style === 'ok') return 'done'
  if (style === 'danger') return 'failed'
  if (style === 'running') return 'running'
  if (style === 'warn' || style === 'attention') return 'waiting'
  return 'pending'
})

// The flower opens once when the run finishes while the node is on screen, never on first render.
const opening = ref(false)
let openTimer: ReturnType<typeof setTimeout> | undefined
watch(state, (now, before) => {
  if (now !== 'done' || before === 'done') return
  opening.value = true
  clearTimeout(openTimer)
  openTimer = setTimeout(() => (opening.value = false), 600)
})
onBeforeUnmount(() => clearTimeout(openTimer))

// Geometry, in the mockup's units (a node is drawn on an 84 unit square around its centre).
const APP = computed(() => roundFlower({ petals: 8, radius: 28 }))
const SKILL = computed(() =>
  SKILL_PETALS === 'pointed'
    ? flower({ petals: 12, length: 30, width: 8.5, shape: 'pointed' })
    : flower({ petals: 12, length: 30, width: 8.5 }),
)
const SUN = flower({ petals: 14, length: 30, width: 6 })
const SEED = seed(56)
const BUD = bud(54)
const LEAF = petal({ length: 48, width: 14 })
const SMALL_LEAF = petal({ length: 34, width: 10 })
// Router petals: the mockup's bloom, length 30 and width 0.36 of it.
const ROUTE_PETAL = petal({ length: 30, width: 10.8 })
const GROUP = roundFlower({ petals: 8, radius: 22 })
const routeColours = computed<AreaColour[]>(() => (props.routes?.length ? props.routes : ['fern', 'hibiscus']))
const routeAngles = computed(() => {
  const count = routeColours.value.length
  return routeColours.value.map((_, index) => index * (360 / count) + (count === 2 ? 60 : 0))
})

/** How many petals a kind has, for the running fill. */
const petalCount = computed(() => {
  if (kind.value === 'app') return APP.value.petals.length
  if (kind.value === 'skill') return SKILL.value.angles.length
  if (kind.value === 'person') return SUN.angles.length
  if (kind.value === 'router') return routeColours.value.length
  return 0
})
const filled = computed(() => {
  if (state.value !== 'running') return petalCount.value
  if (props.progress === undefined) return Math.ceil(petalCount.value / 2)
  return Math.round(Math.min(1, Math.max(0, props.progress)) * petalCount.value)
})
const looping = computed(() => state.value === 'running' && props.progress === undefined)
const pale = computed(() => props.incomplete || state.value === 'pending')
// The edge layer is only needed while some of the plant is pale; the bud has its own dashed edge.
const layers = computed(() => ((pale.value || state.value === 'running') && kind.value !== 'wait' ? ['edge', 'fill'] : ['fill']))

/** Class for petal `index`: filled in colour, or pale while waiting to fill. */
function petalClass(index: number): Record<string, boolean> {
  const lit = !pale.value && index < filled.value
  return { 'node__petal--lit': lit, 'node__petal--loop': looping.value }
}
const petalStyle = (index: number) => ({ '--i': index, '--n': petalCount.value })
// Each route petal takes the colour of the node it leads to, in both its full and its pale state.
function routeVars(colour: AreaColour): Record<string, string> {
  const { strong, soft } = colourVars(colour)
  return { '--c-strong': strong, '--c-soft': soft }
}

const iconSize = computed(() => (kind.value === 'trigger' ? 13 : 15))
const glyphAt = computed(() => {
  if (kind.value === 'trigger') return { x: -10 - iconSize.value / 2, y: -iconSize.value / 2 }
  return { x: -iconSize.value / 2, y: -iconSize.value / 2 }
})
const showGlyph = computed(() => ['app', 'skill', 'person', 'router', 'trigger', 'group'].includes(kind.value))
const glyph = computed<IconName>(() => look.value.icon)

const subtitle = computed(() => props.summary ?? look.value.label)
const accessibleName = computed(() => {
  const parts = [props.title, look.value.label]
  if (props.incomplete) parts.push('needs setup')
  if (props.problem) parts.push('has a problem')
  return parts.filter(Boolean).join(', ')
})
const shownPorts = computed(() => props.ports ?? (kind.value === 'finish' || kind.value === 'stop' ? [] : ['done', 'failed']))
const portClass = (port: string) => (port === 'failed' ? 'node__port--failed' : port === 'done' ? 'node__port--done' : '')
</script>

<template>
  <article
    class="node"
    :class="[
      `node--${kind}`,
      `node--${state}`,
      { 'node--selected': selected, 'node--pale': pale, 'node--opening': opening },
    ]"
    :aria-label="accessibleName"
    :data-kind="kind"
    :data-state="state"
    :style="vars"
  >
    <div class="node__glyph">
      <svg class="node__svg" viewBox="-42 -42 84 84" width="88" height="88" aria-hidden="true" focusable="false">
        <circle v-if="selected" class="node__ring" r="40" />
        <circle v-if="state === 'waiting'" class="node__halo" r="36.5" />

        <!-- Failed nodes droop: the wilt sits on this group, the open-up on the one inside. -->
        <g :transform="state === 'failed' ? 'translate(0 5) rotate(16) scale(0.92 0.84)' : undefined">
          <g class="node__plant">
            <!-- Pale plants are drawn twice: an edge layer behind, then the fill, so overlapping petals
                 show one outline instead of every arc. Cores belong to the fill layer only. -->
            <g v-for="layer in layers" :key="layer" :class="`node__${layer}`">
              <template v-if="kind === 'app'">
                <circle class="node__body" :r="APP.body" />
                <circle
                  v-for="(p, index) in APP.petals"
                  :key="index"
                  class="node__petal"
                  :class="petalClass(index)"
                  :style="petalStyle(index)"
                  :cx="p.cx"
                  :cy="p.cy"
                  :r="p.r"
                />
                <circle v-if="layer === 'fill'" class="node__core" r="11.5" />
              </template>

              <template v-else-if="kind === 'skill'">
                <path
                  v-for="(angle, index) in SKILL.angles"
                  :key="angle"
                  class="node__petal"
                  :class="petalClass(index)"
                  :style="petalStyle(index)"
                  :transform="`rotate(${angle})`"
                  :d="SKILL.petal"
                />
                <circle v-if="layer === 'fill'" class="node__core" r="12" />
              </template>

              <template v-else-if="kind === 'person'">
                <path
                  v-for="(angle, index) in SUN.angles"
                  :key="angle"
                  class="node__petal"
                  :class="petalClass(index)"
                  :style="petalStyle(index)"
                  :transform="`rotate(${angle})`"
                  :d="SUN.petal"
                />
                <circle v-if="layer === 'fill'" class="node__eye" r="14.4" />
              </template>

              <template v-else-if="kind === 'router'">
                <path
                  v-for="(colour, index) in routeColours"
                  :key="index"
                  class="node__petal node__petal--route"
                  :class="petalClass(index)"
                  :style="[petalStyle(index), routeVars(colour)]"
                  :transform="`rotate(${routeAngles[index]})`"
                  :d="ROUTE_PETAL"
                />
                <circle v-if="layer === 'fill'" class="node__eye" r="11" />
              </template>

              <template v-else-if="kind === 'trigger'">
                <path class="node__solid" :d="SEED.body" />
                <circle v-if="layer === 'fill'" class="node__core" :cx="-10" r="10" />
              </template>

              <template v-else-if="kind === 'wait'">
                <path class="node__bud" :d="BUD" />
                <circle class="node__solid" r="5" />
              </template>

              <template v-else-if="kind === 'group'">
                <g
                  v-for="(offset, depth) in [8, 4, 0]"
                  :key="offset"
                  :class="`node__layer node__layer--${depth}`"
                  :transform="`translate(${offset - 4} ${4 - offset})`"
                >
                  <circle class="node__solid" :r="GROUP.body" />
                  <circle v-for="(p, index) in GROUP.petals" :key="index" class="node__solid" :cx="p.cx" :cy="p.cy" :r="p.r" />
                </g>
                <circle v-if="layer === 'fill'" class="node__core" cx="-4" cy="4" r="9.5" />
              </template>

              <template v-else-if="kind === 'stop'">
                <!-- A wilted hibiscus: the stem arches over and the head hangs, two petals fallen. -->
                <path v-if="layer === 'fill'" class="node__stem" d="M-24 36C-26 6 -10 -22 12 -20" />
                <g transform="translate(16 -2) scale(0.7 0.62)">
                  <circle class="node__solid" :r="APP.body" />
                  <circle v-for="(p, index) in APP.petals.slice(1, 7)" :key="index" class="node__solid" :cx="p.cx" :cy="p.cy" :r="p.r" />
                </g>
                <circle class="node__solid" cx="6" cy="26" r="4.2" />
                <circle class="node__solid" cx="20" cy="33" r="3.2" />
              </template>

              <template v-else>
                <!-- finish and data tools: a leaf, the small one for data tools, with a light midrib. -->
                <g :transform="kind === 'data' ? 'translate(-12 12) rotate(62)' : 'translate(-17 15) rotate(62)'">
                  <path class="node__solid" :d="kind === 'data' ? SMALL_LEAF : LEAF" />
                  <path v-if="layer === 'fill'" class="node__rib" :d="kind === 'data' ? 'M0 -4V-28' : 'M0 -4V-40'" />
                </g>
              </template>
            </g>
            <!-- A failed step drops two petals below it. -->
            <template v-if="state === 'failed' && kind !== 'stop'">
              <circle class="node__fallen" cx="12" cy="36" r="4" />
              <circle class="node__fallen" cx="24" cy="31" r="3" />
            </template>
            <UIcon
              v-if="showGlyph"
              class="node__icon"
              :class="{ 'node__icon--on-dark': kind === 'person' || kind === 'router' }"
              :name="glyph"
              weight="fill"
              :size="iconSize"
              :x="kind === 'group' ? glyphAt.x - 4 : glyphAt.x"
              :y="kind === 'group' ? glyphAt.y + 4 : glyphAt.y"
            />
          </g>
        </g>

        <circle v-if="state === 'failed' || problem" class="node__alert" cx="27" cy="-27" r="6" />
      </svg>
      <ul v-if="shownPorts.length" class="node__ports" aria-label="Output ports">
        <li v-for="port in shownPorts" :key="port" class="node__port" :class="portClass(port)" :title="port">
          <span class="node__port-name">{{ port }}</span>
        </li>
      </ul>
    </div>
    <strong class="node__title">{{ title }}</strong>
    <span class="node__summary">{{ subtitle }}</span>
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
  width: 168px;
  text-align: center;
}
.node__glyph {
  position: relative;
  width: 88px;
  height: 88px;
  margin-bottom: var(--space-4);
}
.node__svg {
  overflow: visible;
}

/* Colour: strong for the plant, soft while pale, deep for marks around it. */
.node__body,
.node__petal,
.node__solid {
  fill: var(--c-strong);
}
.node__core {
  fill: var(--wt-surface);
}
.node__eye {
  fill: var(--wt-ink);
}
.node__icon {
  color: var(--c-deep);
}
.node__icon--on-dark {
  color: var(--wt-surface);
}
.node__rib {
  fill: none;
  stroke: var(--wt-surface);
  stroke-width: 2;
  stroke-linecap: round;
}
.node__stem {
  fill: none;
  stroke: var(--wt-fern);
  stroke-width: 3;
  stroke-linecap: round;
}
.node__bud {
  fill: var(--c-soft);
  stroke: var(--c-strong);
  stroke-width: 3.5;
  stroke-dasharray: 5 5;
  stroke-linecap: round;
}
.node__layer--0 {
  opacity: 0.35;
}
.node__layer--1 {
  opacity: 0.6;
}

/* Pale: pending runs and nodes that need setup are the soft tint inside one outline. The edge layer
   draws every shape in the strong colour, 1.5 units wider all round; the fill layer covers it. */
.node__petal:not(.node__petal--lit),
.node--pale .node__body,
.node--pale .node__solid,
.node--running .node__body {
  fill: var(--c-soft);
}
.node__edge * {
  fill: var(--c-strong) !important;
  stroke: var(--c-strong);
  stroke-width: 3;
  stroke-linejoin: round;
  animation: none !important;
}
.node__fallen {
  fill: var(--c-strong);
  opacity: 0.7;
}

/* Running without a known progress: the petals fill clockwise, one after another, and start again.
   With reduced motion the static half fill stays. */
@media (prefers-reduced-motion: no-preference) {
  .node__petal--loop {
    animation: node-petal-fill calc(var(--n) * 260ms) linear infinite;
    animation-delay: calc(var(--i) * 260ms);
  }
  /* The open-up runs on the inner group only, never on the petals, whose turn is an attribute. */
  .node--opening .node__plant {
    transform-box: fill-box;
    transform-origin: center;
    animation: node-open var(--motion-grow) var(--ease-grow);
  }
}
@keyframes node-petal-fill {
  0% {
    fill: var(--c-soft);
  }
  12%,
  70% {
    fill: var(--c-strong);
  }
  82%,
  100% {
    fill: var(--c-soft);
  }
}
@keyframes node-open {
  from {
    transform: scale(0.72);
  }
  to {
    transform: scale(1);
  }
}

.node--failed .node__plant {
  opacity: 0.78;
}
.node__alert {
  fill: var(--wt-hibiscus);
  stroke: var(--wt-surface);
  stroke-width: 2.5;
}
.node__halo {
  fill: none;
  stroke: var(--c-deep);
  stroke-width: 2;
  stroke-dasharray: 6 5;
}
.node__ring {
  fill: none;
  stroke: var(--c-deep);
  stroke-width: 2.5;
  stroke-dasharray: 0.5 5.5;
  stroke-linecap: round;
}

.node__ports {
  position: absolute;
  right: -8px;
  top: 30px;
  display: grid;
  gap: var(--space-10);
  margin: 0;
  padding: 0;
  list-style: none;
}
/* A port is a small bud on the right edge, named on hover. */
.node__port {
  width: 11px;
  height: 13px;
  border: var(--stroke-2) solid var(--wt-surface);
  border-radius: 50% 50% 50% 50% / 62% 62% 38% 38%;
  background: var(--c-strong);
  transform: rotate(90deg);
}
.node__port--done {
  background: var(--wt-fern);
}
.node__port--failed {
  background: var(--wt-hibiscus);
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
.node__summary {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node__title {
  font-size: var(--font-size-14);
  font-weight: var(--weight-bold);
}
.node__summary {
  color: var(--wt-muted);
  font-size: var(--font-size-12);
}
.node__run {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
  font-size: var(--font-size-12);
}
.node__time {
  color: var(--wt-muted);
  font-variant-numeric: tabular-nums;
}

/* Windows High Contrast: the plant in the text colour, its centre in the page colour. */
@media (forced-colors: active) {
  .node__svg {
    forced-color-adjust: none;
  }
  .node__body,
  .node__petal,
  .node__solid,
  .node__eye,
  .node__alert {
    fill: CanvasText;
    stroke: Canvas;
  }
  .node__petal:not(.node__petal--lit),
  .node--pale .node__body,
  .node--pale .node__solid,
  .node--running .node__body {
    fill: Canvas;
    stroke: none;
  }
  .node__edge *,
  .node__fallen {
    fill: CanvasText !important;
    stroke: CanvasText;
  }
  .node__bud {
    fill: Canvas;
    stroke: CanvasText;
  }
  .node__core {
    fill: Canvas;
  }
  .node__icon {
    color: CanvasText;
  }
  .node__icon--on-dark {
    color: Canvas;
  }
  .node__rib,
  .node__stem,
  .node__halo,
  .node__ring {
    stroke: CanvasText;
  }
  .node__port {
    forced-color-adjust: none;
    border-color: Canvas;
    background: CanvasText;
  }
}
</style>
