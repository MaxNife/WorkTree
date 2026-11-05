// Operations console (CP-29). See router/index.ts for how area modules plug into the shell.
import type { RouteRecordRaw } from 'vue-router'
import type { NavItem, PaletteCommand } from '../types'

export const routes: RouteRecordRaw[] = [
  {
    path: '/operations',
    meta: { breadcrumb: 'Operations' },
    children: [
      { path: '', name: 'operations.home', component: () => import('@/views/operations/OperationsHome.vue') },
      {
        path: 'runs',
        meta: { breadcrumb: 'Runs' },
        children: [
          { path: '', name: 'operations.runs', component: () => import('@/views/operations/RunHistory.vue') },
          {
            path: ':runId',
            name: 'operations.run',
            component: () => import('@/views/operations/RunDetail.vue'),
            meta: { breadcrumb: 'Run' },
          },
        ],
      },
      {
        path: 'schedules',
        name: 'operations.schedules',
        component: () => import('@/views/operations/SchedulesView.vue'),
        meta: { breadcrumb: 'Schedules' },
      },
    ],
  },
]

// "Go to Runs" and "Go to Schedules" come from these entries (see navigationCommands).
export const navItems: NavItem[] = [
  {
    id: 'operations',
    label: 'Operations',
    icon: 'operations',
    to: '/operations',
    children: [
      { id: 'operations.dashboard', label: 'Dashboard', icon: 'dashboard', to: '/operations' },
      { id: 'operations.runs', label: 'Runs', icon: 'history', to: '/operations/runs' },
      { id: 'operations.schedules', label: 'Schedules', icon: 'schedule', to: '/operations/schedules' },
    ],
  },
]

// The roles that hold `run.trigger`. The dashboard hosts the dialog: a command can only navigate.
export const commands: PaletteCommand[] = [
  {
    id: 'operations.run-now',
    label: 'Run now',
    group: 'Operations',
    icon: 'play',
    keywords: ['start', 'trigger', 'workflow'],
    roles: ['operator', 'author', 'admin'],
    run: ({ router }) => router.push({ name: 'operations.home', query: { run: '1' } }).then(() => undefined),
  },
]
