import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import './fluent'
import { createAppRouter } from './router'
import { usePreferences } from './stores/preferences'
import './styles/base.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// Theme first, so the first paint already uses the right tokens.
const preferences = usePreferences(pinia)
preferences.apply()
preferences.watchSystem()

app.use(createAppRouter())
app.use(VueQueryPlugin, {
  queryClient: new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1 } } }),
})
app.mount('#app')
