// Pages, data views and saved views (CP-33). See router/index.ts for how area modules plug into the shell.
import type { RouteRecordRaw } from 'vue-router'
import type { NavItem, PaletteCommand } from '../types'

export const routes: RouteRecordRaw[] = [
  {
    path: '/data',
    meta: { breadcrumb: 'Data' },
    children: [{ path: '', name: 'data.home', component: () => import('@/views/data/DataHome.vue') }],
  },
]

export const navItems: NavItem[] = [{ id: 'data', label: 'Data', icon: 'data', to: '/data' }]

export const commands: PaletteCommand[] = []
