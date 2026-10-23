import { beforeEach, describe, expect, it } from 'vitest'
import { applyTheme, resolveTheme } from '@/theme/apply'
import { BRAND, contrastRatio, THEMES, type ThemeName } from '@/theme/tokens'

const asMedia = (matching: string[]) => (query: string) => matching.includes(query)

describe('resolveTheme', () => {
  it('follows the OS in system mode', () => {
    expect(resolveTheme('system', asMedia([]))).toBe('light')
    expect(resolveTheme('system', asMedia(['(prefers-color-scheme: dark)']))).toBe('dark')
  })

  it('uses high contrast when the OS asks for it, even in dark mode', () => {
    expect(resolveTheme('system', asMedia(['(forced-colors: active)', '(prefers-color-scheme: dark)']))).toBe(
      'high-contrast',
    )
    expect(resolveTheme('system', asMedia(['(prefers-contrast: more)']))).toBe('high-contrast')
  })

  it('lets an explicit choice win over the OS', () => {
    expect(resolveTheme('light', asMedia(['(prefers-color-scheme: dark)']))).toBe('light')
    expect(resolveTheme('dark', asMedia([]))).toBe('dark')
  })
})

describe('applyTheme', () => {
  beforeEach(() => document.documentElement.removeAttribute('style'))

  it('writes tokens as CSS custom properties and sets the data attributes', () => {
    applyTheme('dark', 'comfortable')
    const root = document.documentElement
    expect(root.dataset.theme).toBe('dark')
    expect(root.dataset.density).toBe('comfortable')
    expect(root.style.getPropertyValue('--colorNeutralBackground1')).toBe(String(THEMES.dark.colorNeutralBackground1))
    expect(root.style.getPropertyValue('--colorBrandBackground')).toBe(BRAND.base)
  })
})

describe('tokens', () => {
  const names = Object.keys(THEMES) as ThemeName[]

  it('defines the same tokens in every theme', () => {
    const light = Object.keys(THEMES.light).sort()
    for (const name of names) expect(Object.keys(THEMES[name]).sort()).toEqual(light)
  })

  it('has a green Work and a brown Tree in the wordmark', () => {
    expect(THEMES.light.wordmarkWork).toBe('#107C10')
    expect(THEMES.light.wordmarkTree).toBe('#7a4a1e')
  })

  it('uses the Fluent green as the brand accent', () => {
    expect(THEMES.light.colorBrandBackground).toBe('#107C10')
  })

  // WCAG AA: 4.5:1 for normal text.
  const textPairs: [string, string][] = [
    ['colorNeutralForeground1', 'colorNeutralBackground1'],
    ['colorNeutralForeground2', 'colorNeutralBackground1'],
    ['colorNeutralForeground3', 'colorNeutralBackground1'],
    ['colorNeutralForegroundOnBrand', 'colorBrandBackground'],
    ['colorNeutralForegroundOnBrand', 'colorBrandBackgroundHover'],
    ['colorBrandForeground1', 'colorNeutralBackground1'],
    ['colorBrandForegroundLink', 'colorNeutralBackground1'],
    ['colorPaletteGreenForeground1', 'colorPaletteGreenBackground1'],
    ['colorPaletteRedForeground1', 'colorPaletteRedBackground1'],
    ['colorPaletteYellowForeground1', 'colorPaletteYellowBackground1'],
    ['colorPaletteDarkOrangeForeground1', 'colorPaletteDarkOrangeBackground1'],
    ['colorBrandForeground1', 'colorBrandBackground2'],
    ['wordmarkWork', 'colorNeutralBackground1'],
    ['wordmarkTree', 'colorNeutralBackground1'],
  ]
  for (const theme of names) {
    it.each(textPairs)(`${theme}: %s on %s meets 4.5:1`, (fg, bg) => {
      const ratio = contrastRatio(String(THEMES[theme][fg]), String(THEMES[theme][bg]))
      expect(ratio).toBeGreaterThanOrEqual(4.5)
    })
  }

  it('keeps the focus ring visible against the page in every theme', () => {
    for (const theme of names) {
      expect(contrastRatio(String(THEMES[theme].colorStrokeFocus2), String(THEMES[theme].colorNeutralBackground1))).toBeGreaterThanOrEqual(3)
    }
  })
})
