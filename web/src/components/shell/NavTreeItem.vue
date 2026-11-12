<script setup lang="ts">
// One sidebar entry and, when expanded, its children (static or loaded on demand). Links and
// disclosure buttons only, so Tab and Enter/Space are enough to reach and operate everything.
import { useQuery } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import LeafMark from '@/components/LeafMark.vue'
import UIcon from '@/components/UIcon.vue'
import { areaColour } from '@/theme/areas'
import { allowed, type NavItem } from '@/router/types'
import { useSession } from '@/stores/session'
import { useShellLayout } from './layout'
import { pathMatches, useNavRegistry } from './navMatch'

const props = defineProps<{ item: NavItem; depth: number; collapsed: boolean }>()

const route = useRoute()
const layout = useShellLayout()
const session = useSession()

const expandable = computed(() => !props.collapsed && Boolean(props.item.children?.length || props.item.loadChildren))
const open = computed(() => expandable.value && layout.isExpanded(props.item.id))
const registry = useNavRegistry()
// The one current entry (aria-current="page"), and, for an area row, whether the page is in that area.
const current = computed(() => registry?.isCurrent(props.item.id) ?? false)
const inArea = computed(() => props.depth === 0 && Boolean(props.item.to) && pathMatches(props.item.to ?? '', route.path))
const colour = computed(() => (props.depth === 0 ? areaColour(props.item.id) : undefined))

watch(
  () => props.item.to,
  (to, before) => {
    if (!registry) return
    if (before !== undefined) registry.unregister(props.item.id)
    if (to) registry.register({ id: props.item.id, to, depth: props.depth })
  },
  { immediate: true },
)
onBeforeUnmount(() => registry?.unregister(props.item.id))

const loaded = useQuery({
  queryKey: computed(() => ['nav', props.item.id]),
  queryFn: () => (props.item.loadChildren ? props.item.loadChildren() : Promise.resolve([])),
  enabled: computed(() => Boolean(props.item.loadChildren) && open.value && session.isAuthenticated),
})

const children = computed(() =>
  (props.item.children ?? loaded.data.value ?? []).filter((child) => allowed(child.roles, session.roles)),
)
const groupId = computed(() => `nav-group-${props.item.id.replace(/[^\w-]/g, '_')}`)

function toggle(): void {
  layout.setExpanded(props.item.id, !open.value)
}
</script>

<template>
  <li class="nav-item">
    <div
      class="nav-item__row"
      :class="{ 'is-current': current, 'is-in-area': inArea, 'nav-item__row--rail': collapsed }"
      :style="{ '--depth': depth, '--area-soft': colour ? `var(--wt-${colour === 'night-soil' ? 'sunken' : `${colour}-soft`})` : undefined }"
    >
      <button
        v-if="expandable && item.to"
        type="button"
        class="nav-item__toggle"
        :aria-expanded="open"
        :aria-controls="groupId"
        :aria-label="`${item.label} items`"
        @click="toggle"
      >
        <UIcon :name="open ? 'chevron-down' : 'chevron-right'" :size="12" />
      </button>
      <span v-else-if="!collapsed && item.to" class="nav-item__spacer" />
      <!-- custom: aria-current follows the one current entry, not RouterLink's exact-active rule. -->
      <RouterLink v-if="item.to" v-slot="{ href, navigate }" :to="item.to" custom>
        <a
          :href="href"
          class="nav-item__link"
          :aria-current="current ? 'page' : undefined"
          :aria-label="collapsed ? item.label : undefined"
          :title="collapsed ? item.label : undefined"
          @click="navigate"
        >
          <span v-if="collapsed && colour" class="nav-item__rail-leaf">
            <UIcon v-if="item.icon" :name="item.icon" :size="18" />
          </span>
          <LeafMark v-else-if="colour" :colour="colour" :size="12" class="nav-item__leaf" />
          <UIcon v-else-if="item.icon" :name="item.icon" :size="depth === 0 ? 20 : 16" />
          <span v-if="!collapsed" class="nav-item__label">{{ item.label }}</span>
        </a>
      </RouterLink>
      <button
        v-else
        type="button"
        class="nav-item__link nav-item__link--group"
        :aria-expanded="open"
        :aria-controls="groupId"
        @click="toggle"
      >
        <UIcon :name="open ? 'chevron-down' : 'chevron-right'" :size="12" class="nav-item__chevron" />
        <UIcon v-if="item.icon" :name="item.icon" :size="16" />
        <span class="nav-item__label">{{ item.label }}</span>
      </button>
    </div>
    <ul v-if="open" :id="groupId" class="nav-item__children">
      <li v-if="loaded.isPending.value && item.loadChildren && !item.children" class="nav-item__note" :style="{ '--depth': depth + 1 }">
        Loading...
      </li>
      <li v-else-if="loaded.isError.value" class="nav-item__note" :style="{ '--depth': depth + 1 }">Could not load.</li>
      <li v-else-if="children.length === 0" class="nav-item__note" :style="{ '--depth': depth + 1 }">Nothing here yet.</li>
      <NavTreeItem v-for="child in children" :key="child.id" :item="child" :depth="depth + 1" :collapsed="collapsed" />
    </ul>
  </li>
</template>

<style scoped>
.nav-item {
  list-style: none;
}
.nav-item__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-left: calc(var(--depth) * var(--space-12));
  border-radius: var(--wt-radius);
}
.nav-item__row:hover {
  background: var(--wt-surface-hover);
}
.nav-item__row > .nav-item__link {
  color: var(--wt-text-secondary);
}
.nav-item__row.is-in-area > .nav-item__link,
.nav-item__row.is-current > .nav-item__link {
  color: var(--wt-ink);
  font-weight: var(--weight-semibold);
}
.nav-item__row.is-current {
  background: var(--wt-sunken);
}
.nav-item__leaf {
  margin: 0 var(--space-4);
}
/* The rail keeps each area's glyph, set on a leaf of its soft tint, so colour is not the only cue. */
.nav-item__rail-leaf {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--wt-leaf);
  background: var(--area-soft);
  color: var(--wt-ink);
}
.nav-item__row--rail.is-current,
.nav-item__row--rail.is-in-area {
  background: var(--wt-sunken);
}
.nav-item__toggle,
.nav-item__spacer {
  flex: none;
  width: 20px;
}
.nav-item__toggle,
.nav-item__link {
  display: inline-flex;
  align-items: center;
  border: 0;
  border-radius: var(--wt-radius);
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.nav-item__toggle {
  justify-content: center;
  height: var(--wt-control-height);
  color: var(--wt-muted);
}
.nav-item__link {
  flex: 1;
  gap: var(--space-8);
  min-width: 0;
  min-height: var(--wt-control-height);
  padding: 0 var(--space-8) 0 var(--space-4);
  text-align: left;
  text-decoration: none;
}
.nav-item__link--group {
  padding-left: var(--space-2);
}
.nav-item__chevron {
  color: var(--wt-muted);
}
.nav-item__row--rail .nav-item__link {
  justify-content: center;
  padding: 0;
}
.nav-item__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nav-item__children {
  margin: 0;
  padding: 0;
}
.nav-item__note {
  list-style: none;
  padding: var(--space-4) 0 var(--space-4) calc(var(--depth) * var(--space-12) + 24px);
  color: var(--wt-muted);
  font-size: var(--font-size-12);
}
</style>
