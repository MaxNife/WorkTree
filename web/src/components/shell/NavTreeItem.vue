<script setup lang="ts">
// One sidebar entry and, when expanded, its children (static or loaded on demand). Links and
// disclosure buttons only, so Tab and Enter/Space are enough to reach and operate everything.
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import UIcon from '@/components/UIcon.vue'
import { allowed, type NavItem } from '@/router/types'
import { useSession } from '@/stores/session'
import { useShellLayout } from './layout'

const props = defineProps<{ item: NavItem; depth: number; collapsed: boolean }>()

const route = useRoute()
const layout = useShellLayout()
const session = useSession()

const expandable = computed(() => !props.collapsed && Boolean(props.item.children?.length || props.item.loadChildren))
const open = computed(() => expandable.value && layout.isExpanded(props.item.id))
const active = computed(() => {
  const to = props.item.to
  return Boolean(to) && (route.path === to || route.path.startsWith(`${to}/`))
})

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
    <div class="nav-item__row" :class="{ 'is-active': active, 'nav-item__row--rail': collapsed }" :style="{ '--depth': depth }">
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
      <RouterLink
        v-if="item.to"
        :to="item.to"
        class="nav-item__link"
        :aria-label="collapsed ? item.label : undefined"
        :title="collapsed ? item.label : undefined"
      >
        <UIcon v-if="item.icon" :name="item.icon" :size="depth === 0 ? 20 : 16" />
        <span v-if="!collapsed" class="nav-item__label">{{ item.label }}</span>
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
  border-radius: var(--uaf-radius);
}
.nav-item__row:hover {
  background: var(--uaf-surface-hover);
}
.nav-item__row.is-active {
  background: var(--uaf-surface-selected);
}
.nav-item__row.is-active > .nav-item__link {
  font-weight: var(--weight-semibold);
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
  border-radius: var(--uaf-radius);
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.nav-item__toggle {
  justify-content: center;
  height: var(--uaf-control-height);
  color: var(--uaf-text-muted);
}
.nav-item__link {
  flex: 1;
  gap: var(--space-8);
  min-width: 0;
  min-height: var(--uaf-control-height);
  padding: 0 var(--space-8) 0 var(--space-4);
  text-align: left;
  text-decoration: none;
}
.nav-item__link--group {
  padding-left: var(--space-2);
}
.nav-item__chevron {
  color: var(--uaf-text-muted);
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
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
}
</style>
