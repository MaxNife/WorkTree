import { VueQueryPlugin, QueryCache, QueryClient, MutationCache } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import { ApiError } from './api/client'
import App from './App.vue'
import { createAppRouter } from './router'
import { usePreferences } from './stores/preferences'
import { useSession } from './stores/session'
import { useToast } from './stores/toast'
import './styles/base.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// Theme first, so the first paint already uses the right tokens.
const preferences = usePreferences(pinia)
preferences.apply()
preferences.watchSystem()

const router = createAppRouter(undefined, pinia)
app.use(router)

// A 401 from any query or mutation means the session ended (expired or signed out elsewhere).
function onApiError(error: unknown): void {
  const session = useSession(pinia)
  if (!(error instanceof ApiError) || error.status !== 401 || !session.isAuthenticated) return
  session.expire()
  queryClient.clear()
  useToast().info('Your session has ended. Sign in again to continue.')
  void router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: onApiError }),
  mutationCache: new MutationCache({ onError: onApiError }),
  // Retry once, but not client errors (4xx): asking again gives the same answer.
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: (failures, error) => failures < 1 && !(error instanceof ApiError && error.status < 500),
    },
  },
})
app.use(VueQueryPlugin, { queryClient })
app.mount('#app')
