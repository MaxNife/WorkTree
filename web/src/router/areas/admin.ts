// Admin (CP-32). See router/index.ts for how area modules plug into the shell.
// Admin-only in the UI; the API enforces the same rule on every call.
import type { RouteRecordRaw } from 'vue-router'
import type { NavItem, PaletteCommand } from '../types'

export const routes: RouteRecordRaw[] = [
  {
    path: '/admin',
    meta: { breadcrumb: 'Admin', roles: ['admin'] },
    children: [{ path: '', name: 'admin.home', component: () => import('@/views/admin/AdminHome.vue') }],
  },
]

export const navItems: NavItem[] = [{ id: 'admin', label: 'Admin', icon: 'admin', to: '/admin', roles: ['admin'] }]

export const commands: PaletteCommand[] = []
