import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePreferences } from '@/stores/preferences'

describe('preferences store', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.removeAttribute('style')
    setActivePinia(createPinia())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('defaults to following the system in compact density', () => {
    const preferences = usePreferences()
    expect(preferences.mode).toBe('system')
    expect(preferences.density).toBe('compact')
  })

  it('applies and remembers the user choice', () => {
    const preferences = usePreferences()
    preferences.setMode('dark')
    preferences.setDensity('comfortable')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.dataset.density).toBe('comfortable')

    setActivePinia(createPinia())
    const reloaded = usePreferences()
    expect(reloaded.mode).toBe('dark')
    expect(reloaded.density).toBe('comfortable')
  })

  it('ignores a corrupt saved value', () => {
    window.localStorage.setItem('uaf.preferences', '{"mode":"neon","density":7}')
    const preferences = usePreferences()
    expect(preferences.mode).toBe('system')
    expect(preferences.density).toBe('compact')
  })

  it('still works when storage throws', () => {
    const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } }
    vi.stubGlobal('localStorage', broken)
    const preferences = usePreferences()
    expect(() => preferences.setMode('light')).not.toThrow()
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})
