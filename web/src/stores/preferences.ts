import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { applyTheme, DENSITIES, resolveTheme, THEME_MODES, type Density, type ThemeMode } from '@/theme/apply'
import { readStored } from '@/compat'

const STORAGE_KEY = 'worktree.preferences'
const SYSTEM_QUERIES = ['(prefers-color-scheme: dark)', '(forced-colors: active)', '(prefers-contrast: more)']

interface Saved {
  mode: ThemeMode
  density: Density
}

function isMode(value: unknown): value is ThemeMode {
  return THEME_MODES.includes(value as ThemeMode)
}

function isDensity(value: unknown): value is Density {
  return DENSITIES.includes(value as Density)
}

// Storage can be missing or throw (private windows, blocked site data); the app works without it.
function load(): Saved {
  const fallback: Saved = { mode: 'system', density: 'compact' }
  try {
    const raw = readStored(STORAGE_KEY, 'uaf.preferences')
    if (!raw) return fallback
    const data = JSON.parse(raw) as Partial<Saved>
    return {
      mode: isMode(data.mode) ? data.mode : fallback.mode,
      density: isDensity(data.density) ? data.density : fallback.density,
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
  // matchMedia is not reactive, so a change in the OS has to invalidate the theme by hand.
  const systemChanges = ref(0)
  const theme = computed(() => {
    void systemChanges.value
    return resolveTheme(mode.value)
  })

  function apply(): void {
    applyTheme(theme.value, density.value)
  }

  function saveAndApply(): void {
    save({ mode: mode.value, density: density.value })
    apply()
  }

  function setMode(next: ThemeMode): void {
    mode.value = next
    saveAndApply()
  }

  function setDensity(next: Density): void {
    density.value = next
    saveAndApply()
  }

  /** Follow the OS while the mode is 'system'. Returns a function that stops listening. */
  function watchSystem(): () => void {
    if (typeof window.matchMedia !== 'function') return () => undefined
    const queries = SYSTEM_QUERIES.map((query) => window.matchMedia(query))
    const onChange = () => {
      systemChanges.value += 1
      if (mode.value === 'system') apply()
    }
    queries.forEach((query) => query.addEventListener('change', onChange))
    return () => queries.forEach((query) => query.removeEventListener('change', onChange))
  }

  return { mode, density, theme, apply, setMode, setDensity, watchSystem }
})
