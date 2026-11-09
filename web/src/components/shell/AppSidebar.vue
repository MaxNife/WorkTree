<script setup lang="ts">
// Collapsible left sidebar (Notion/Azure style). Collapsed, it is an icon rail with the five areas.
import { computed } from 'vue'
import UIcon from '@/components/UIcon.vue'
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
import { AREAS } from '@/router/areas'
import { allowed } from '@/router/types'
import { useSession } from '@/stores/session'
import { useShellLayout } from './layout'
import NavTreeItem from './NavTreeItem.vue'

const layout = useShellLayout()
const session = useSession()
const items = computed(() => AREAS.flatMap((area) => area.navItems).filter((item) => allowed(item.roles, session.roles)))
</script>

<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': layout.collapsed }">
    <div class="sidebar__head">
      <RouterLink to="/" class="sidebar__brand" aria-label="WorkTree home">
        <WorkTreeLogo :mark-only="layout.collapsed" />
      </RouterLink>
      <button
        type="button"
        class="sidebar__toggle"
        :aria-label="layout.collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        :title="layout.collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        :aria-expanded="!layout.collapsed"
        aria-controls="app-nav"
        @click="layout.toggleCollapsed()"
      >
        <UIcon :name="layout.collapsed ? 'panel-expand' : 'panel-collapse'" :size="20" />
      </button>
    </div>
    <nav id="app-nav" class="sidebar__nav" aria-label="Main">
      <ul class="sidebar__list">
        <NavTreeItem v-for="item in items" :key="item.id" :item="item" :depth="0" :collapsed="layout.collapsed" />
      </ul>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: 240px;
  min-height: 0;
  border-right: var(--stroke-1) solid var(--uaf-border);
  background: var(--uaf-surface-sunken);
}
.sidebar--collapsed {
  width: 52px;
}
.sidebar__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  padding: var(--space-8) var(--space-8) var(--space-8) var(--space-12);
}
.sidebar--collapsed .sidebar__head {
  flex-direction: column;
  padding: var(--space-8) var(--space-4);
}
.sidebar__brand {
  display: inline-flex;
  border-radius: var(--uaf-radius);
  text-decoration: none;
}
.sidebar__toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--uaf-control-height);
  height: var(--uaf-control-height);
  border: 0;
  border-radius: var(--uaf-radius);
  background: none;
  color: var(--uaf-text-muted);
  cursor: pointer;
}
.sidebar__toggle:hover {
  background: var(--uaf-surface-hover);
  color: var(--uaf-text);
}
.sidebar__nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-8);
}
.sidebar--collapsed .sidebar__nav {
  padding: var(--space-4);
}
.sidebar__list {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
}
</style>
