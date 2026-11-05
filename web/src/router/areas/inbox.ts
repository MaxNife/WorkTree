// Task Inbox (CP-30). See router/index.ts for how area modules plug into the shell.
import type { RouteRecordRaw } from 'vue-router'
import type { NavItem, PaletteCommand } from '../types'

export const routes: RouteRecordRaw[] = [
  {
    path: '/inbox',
    meta: { breadcrumb: 'Inbox' },
    children: [{ path: '', name: 'inbox.home', component: () => import('@/views/inbox/InboxHome.vue') }],
  },
]

export const navItems: NavItem[] = [{ id: 'inbox', label: 'Inbox', icon: 'inbox', to: '/inbox' }]

export const commands: PaletteCommand[] = []
