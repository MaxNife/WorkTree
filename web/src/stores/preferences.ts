import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { applyTheme, resolveTheme, type Density, type ThemeMode } from '@/theme/apply'

const STORAGE_KEY = 'uaf.preferences'
const MODES: ThemeMode[] = ['system', 'light', 'dark', 'high-contrast']
const DENSITIES: Density[] = ['compact', 'comfortable']

interface Saved {
  mode: ThemeMode
  density: Density
}

// Storage can be missing or throw (private windows, blocked site data); the app works without it.
function load(): Saved {
  const fallback: Saved = { mode: 'system', density: 'compact' }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return fallback
    const data = JSON.parse(raw) as Partial<Saved>
    return {
      mode: MODES.includes(data.mode as ThemeMode) ? (data.mode as ThemeMode) : fallback.mode,
      density: DENSITIES.includes(data.density as Density) ? (data.density as Density) : fallback.density,
    }
  } catch {
    return fallback
  }
}

function save(value: Saved): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // not persisted; the choice still applies for this session
  }
}

export const usePreferences = defineStore('preferences', () => {
  const initial = load()
  const mode = ref<ThemeMode>(initial.mode)
  const density = ref<Density>(initial.density)
  const theme = computed(() => resolveTheme(mode.value))

  function apply(): void {
    applyTheme(resolveTheme(mode.value), density.value)
  }

  function setMode(next: ThemeMode): void {
    mode.value = next
    save({ mode: mode.value, density: density.value })
    apply()
  }

  function setDensity(next: Density): void {
    density.value = next
    save({ mode: mode.value, density: density.value })
    apply()
  }

  /** Follow the OS while the mode is 'system'. Returns a function that stops listening. */
  function watchSystem(): () => void {
    if (typeof window.matchMedia !== 'function') return () => undefined
    const queries = ['(prefers-color-scheme: dark)', '(forced-colors: active)', '(prefers-contrast: more)'].map((q) =>
      window.matchMedia(q),
    )
    const onChange = () => {
      if (mode.value === 'system') apply()
    }
    queries.forEach((q) => q.addEventListener('change', onChange))
    return () => queries.forEach((q) => q.removeEventListener('change', onChange))
  }

  return { mode, density, theme, apply, setMode, setDensity, watchSystem }
})
