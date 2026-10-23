import { createRouter, createWebHistory } from 'vue-router'

// CP-27 only has the foundation pages. CP-28 adds the app shell, then each console is added
// as its checkpoint lands (Operations CP-29, Inbox CP-30, Studio CP-31, Admin CP-32, Data CP-33).
export const routes = [
  { path: '/', name: 'home', component: () => import('@/views/HomeView.vue'), meta: { title: 'Home' } },
  {
    path: '/design',
    name: 'design',
    component: () => import('@/views/DesignView.vue'),
    meta: { title: 'Design language' },
  },
]

export function createAppRouter(history = createWebHistory()) {
  return createRouter({ history, routes })
}
