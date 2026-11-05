// Shell layout state remembered per browser: sidebar collapse and which sidebar groups are open.
import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'uaf.shell'

interface Saved {
  collapsed: boolean
  expanded: string[]
}

// Storage can be missing or throw (private windows, blocked site data); the shell works without it.
function load(): Saved {
  const fallback: Saved = { collapsed: false, expanded: [] }
  try {
    const data = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null') as Partial<Saved> | null
    if (!data) return fallback
    return {
      collapsed: data.collapsed === true,
      expanded: Array.isArray(data.expanded) ? data.expanded.filter((id) => typeof id === 'string') : [],
    }
  } catch {
    return fallback
  }
}

export const useShellLayout = defineStore('shell-layout', () => {
  const initial = load()
  const collapsed = ref(initial.collapsed)
  const expanded = ref<string[]>(initial.expanded)

  function save(): void {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ collapsed: collapsed.value, expanded: expanded.value }))
    } catch {
      // not persisted; the choice still applies for this session
    }
  }

  function setCollapsed(value: boolean): void {
    collapsed.value = value
    save()
  }

  function toggleCollapsed(): void {
    setCollapsed(!collapsed.value)
  }

  function isExpanded(id: string): boolean {
    return expanded.value.includes(id)
  }

  function setExpanded(id: string, open: boolean): void {
    expanded.value = open ? [...new Set([...expanded.value, id])] : expanded.value.filter((x) => x !== id)
    save()
  }

  return { collapsed, expanded, setCollapsed, toggleCollapsed, isExpanded, setExpanded }
})
