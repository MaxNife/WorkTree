// Operations console (CP-29). See router/index.ts for how area modules plug into the shell.
import type { RouteRecordRaw } from 'vue-router'
import type { NavItem, PaletteCommand } from '../types'

export const routes: RouteRecordRaw[] = [
  {
    path: '/operations',
    meta: { breadcrumb: 'Operations' },
    children: [
      { path: '', name: 'operations.home', component: () => import('@/views/operations/OperationsHome.vue') },
    ],
  },
]

export const navItems: NavItem[] = [{ id: 'operations', label: 'Operations', icon: 'operations', to: '/operations' }]

export const commands: PaletteCommand[] = []
