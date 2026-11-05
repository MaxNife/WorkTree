// Workflow Studio (CP-31). See router/index.ts for how area modules plug into the shell.
import type { RouteRecordRaw } from 'vue-router'
import { apiGet } from '@/api/client'
import type { NavItem, PaletteCommand } from '../types'

const UNFILED = 'Unfiled'

/** The sidebar tree under Studio: workflows grouped by folder, unfiled ones last. */
export async function loadWorkflowTree(): Promise<NavItem[]> {
  const rows = await apiGet('/api/workflows')
  const folders = new Map<string, NavItem[]>()
  for (const row of rows) {
    const id = String(row.id ?? '')
    if (!id) continue
    const folder = typeof row.folder === 'string' && row.folder.trim() ? row.folder.trim() : UNFILED
    const workflow: NavItem = {
      id: `studio.workflow.${id}`,
      label: String(row.name ?? id),
      icon: 'workflow',
      to: `/studio/workflows/${encodeURIComponent(id)}`,
    }
    folders.set(folder, [...(folders.get(folder) ?? []), workflow])
  }
  const names = [...folders.keys()].filter((name) => name !== UNFILED).sort((a, b) => a.localeCompare(b))
  // With no folders at all, list the workflows directly.
  if (names.length === 0) return folders.get(UNFILED) ?? []
  if (folders.has(UNFILED)) names.push(UNFILED)
  return names.map((name) => ({ id: `studio.folder.${name}`, label: name, icon: 'folder', children: folders.get(name) }))
}

export const routes: RouteRecordRaw[] = [
  {
    path: '/studio',
    meta: { breadcrumb: 'Studio' },
    children: [
      { path: '', name: 'studio.home', component: () => import('@/views/studio/StudioHome.vue') },
      {
        path: 'workflows/:workflowId',
        name: 'studio.workflow',
        component: () => import('@/views/studio/StudioHome.vue'),
        meta: { breadcrumb: (route) => String(route.params.workflowId ?? 'Workflow') },
      },
    ],
  },
]

export const navItems: NavItem[] = [
  { id: 'studio', label: 'Studio', icon: 'studio', to: '/studio', loadChildren: loadWorkflowTree },
]

export const commands: PaletteCommand[] = [
  {
    id: 'studio.refresh-tree',
    label: 'Refresh the workflow list',
    group: 'Studio',
    icon: 'refresh',
    keywords: ['reload', 'sidebar'],
    run: ({ queryClient }) => queryClient.invalidateQueries({ queryKey: ['nav'] }),
  },
]
