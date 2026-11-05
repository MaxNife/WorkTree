// Routes are assembled from the area modules; the sidebar and the command palette read the same modules.
//
// Adding a screen (CP-29 to CP-33): edit only router/areas/<area>.ts and views/<area>/.
//   routes    children of the area route. Name them '<area>.<page>'. `meta.breadcrumb` (text or
//             (route) => text) adds a crumb; `meta.roles` limits access (the API still enforces it).
//   navItems  sidebar entries: { id, label, icon, to, roles?, children?, loadChildren? }.
//   commands  palette entries: { id, label, group, icon?, keywords?, roles?, run({ router, queryClient, toast }) }.
// Screens use <AppPage title> (slots: actions, commands, messages), MessageBar, useToast() from
// stores/toast and useCrumbLabel() from components/shell/breadcrumbs to name the current crumb.
import type { Pinia } from 'pinia'
import { createRouter, createWebHistory, type RouteRecordRaw, type RouterHistory } from 'vue-router'
import AppShell from '@/components/shell/AppShell.vue'
import { useSession } from '@/stores/session'
import { AREAS } from './areas'
import { allowed, safeRedirect } from './types'

const notice = () => import('@/components/shell/ShellNotice.vue')

export const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: 'Sign in' },
  },
  {
    path: '/',
    component: AppShell,
    children: [
      { path: '', name: 'home', redirect: '/operations' },
      ...AREAS.flatMap((area) => area.routes),
      {
        path: '/design',
        name: 'design',
        component: () => import('@/views/DesignView.vue'),
        meta: { breadcrumb: 'Design language' },
      },
      {
        path: '/forbidden',
        name: 'forbidden',
        component: notice,
        props: {
          title: 'You do not have access',
          description: 'This page needs a role you do not have. Ask an administrator if you need it.',
        },
        meta: { breadcrumb: 'No access' },
      },
      {
        path: '/:pathMatch(.*)*',
        name: 'not-found',
        component: notice,
        props: { title: 'Page not found', description: 'Check the address, or find the page another way.' },
        meta: { breadcrumb: 'Not found' },
      },
    ],
  },
]

/** Signed-out users go to the login page; role-limited pages need one of their roles. */
export function installGuards(router: ReturnType<typeof createRouter>, pinia?: Pinia): void {
  router.beforeEach(async (to) => {
    const session = useSession(pinia)
    await session.ensureLoaded()
    if (to.meta.public) {
      return to.name === 'login' && session.isAuthenticated ? (safeRedirect(to.query.redirect) ?? '/') : true
    }
    if (!session.isAuthenticated) {
      return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
    }
    if (!to.matched.every((record) => allowed(record.meta.roles, session.roles))) return { name: 'forbidden' }
    return true
  })

  router.afterEach((to) => {
    const label = [...to.matched].reverse().find((record) => record.meta.title || record.meta.breadcrumb)?.meta
    const title = label?.title ?? (typeof label?.breadcrumb === 'string' ? label.breadcrumb : label?.breadcrumb?.(to))
    document.title = title ? `${title} - WorkTree` : 'WorkTree'
  })
}

export function createAppRouter(history: RouterHistory = createWebHistory(), pinia?: Pinia) {
  const router = createRouter({ history, routes })
  installGuards(router, pinia)
  return router
}
