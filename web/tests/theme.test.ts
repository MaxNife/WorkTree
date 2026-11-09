import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import { applyTheme, resolveTheme } from '@/theme/apply'
import { FAMILIES, FAMILY_NAMES } from '@/theme/families'
import { BRAND, contrastRatio, THEMES, type ThemeName } from '@/theme/tokens'

const asMedia = (matching: string[]) => (query: string) => matching.includes(query)

const WEB = resolve(__dirname, '..')
const SRC = join(WEB, 'src')
const baseCss = readFileSync(join(SRC, 'styles', 'base.css'), 'utf8')

function filesIn(folder: string): string[] {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name)
    return statSync(path).isDirectory() ? filesIn(path) : [path]
  })
}

/** The theme token behind a --uaf-* variable, as base.css maps it. */
function tokenBehind(variable: string): string {
  const match = new RegExp(`${variable}: var\\(--([\\w-]+)\\)`).exec(baseCss)
  if (!match?.[1]) throw new Error(`${variable} is not mapped in base.css`)
  return match[1]
}

const colour = (theme: ThemeName, variable: string): string => String(THEMES[theme][tokenBehind(variable)])

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
    expect(root.style.getPropertyValue('--color-surface')).toBe(String(THEMES.dark['color-surface']))
    expect(root.style.getPropertyValue('--color-accent')).toBe(BRAND.base)
  })
})

describe('tokens', () => {
  const names = Object.keys(THEMES) as ThemeName[]
  const surfaces = ['--uaf-page', '--uaf-surface', '--uaf-surface-sunken']

  it('defines the same tokens in every theme', () => {
    const light = Object.keys(THEMES.light).sort()
    for (const name of names) expect(Object.keys(THEMES[name]).sort()).toEqual(light)
  })

  it('has a green Work and a brown Tree in the wordmark', () => {
    expect(THEMES.light['wordmark-work']).toBe('#107C10')
    expect(THEMES.light['wordmark-tree']).toBe('#7a4a1e')
  })

  it('uses WorkTree green as the accent', () => {
    expect(THEMES.light['color-accent']).toBe('#107C10')
  })

  it('names no token after another design system', () => {
    for (const name of Object.keys(THEMES.light)) expect(name).toMatch(/^[a-z0-9-]+$/)
  })

  // WCAG AA: 4.5:1 for normal text.
  const textPairs: [string, string][] = [
    ['--uaf-text-secondary', '--uaf-surface'],
    ['--uaf-on-accent', '--uaf-accent'],
    ['--uaf-on-accent', '--uaf-accent-hover'],
    ['--uaf-on-accent', '--uaf-accent-pressed'],
    ['--uaf-accent-text', '--uaf-accent-tint'],
    ['--uaf-ok', '--uaf-ok-bg'],
    ['--uaf-danger', '--uaf-danger-bg'],
    ['--uaf-warn', '--uaf-warn-bg'],
    ['--uaf-attention', '--uaf-attention-bg'],
  ]
  for (const theme of names) {
    it.each(textPairs)(`${theme}: %s on %s meets 4.5:1`, (fg, bg) => {
      expect(contrastRatio(colour(theme, fg), colour(theme, bg))).toBeGreaterThanOrEqual(4.5)
    })
  }

  it.each(names)('%s: body, muted, link, accent and error text meet 4.5:1 on every surface', (theme) => {
    for (const text of ['--uaf-text', '--uaf-text-muted', '--uaf-link', '--uaf-accent-text', '--uaf-danger']) {
      for (const surface of surfaces) {
        expect(contrastRatio(colour(theme, text), colour(theme, surface)), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it.each(names)('%s: the wordmark meets 4.5:1 on the page and the surface', (theme) => {
    for (const part of ['wordmark-work', 'wordmark-tree']) {
      for (const surface of ['--uaf-page', '--uaf-surface']) {
        expect(contrastRatio(String(THEMES[theme][part]), colour(theme, surface)), `${part} on ${surface}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  // Everything a status dot can be painted with, read from the component so a remap is caught.
  const badge = readFileSync(join(SRC, 'components', 'StatusBadge.vue'), 'utf8')
  const dots = [...badge.matchAll(/--dot: var\((--uaf-[\w-]+)\)/g)].map((match) => match[1] ?? '')

  it('finds a colour for every status kind', () => {
    expect(dots).toHaveLength(6)
  })

  // WCAG 1.4.11: 3:1 for a meaningful mark against what is next to it.
  it.each(names)('%s: every status dot meets 3:1 on every surface', (theme) => {
    for (const dot of dots) {
      for (const surface of surfaces) {
        expect(contrastRatio(colour(theme, dot), colour(theme, surface)), `${dot} on ${surface}`).toBeGreaterThanOrEqual(3)
      }
    }
  })

  it.each(names)('%s: the edge of a text field, checkbox or switch meets 3:1 on every surface', (theme) => {
    for (const surface of surfaces) {
      expect(contrastRatio(colour(theme, '--uaf-border-control'), colour(theme, surface)), surface).toBeGreaterThanOrEqual(3)
    }
  })

  // The tick of a checkbox and the thumb of a switch sit in the surface colour on these fills.
  it.each(names)('%s: a checked checkbox or switch keeps 3:1 for its mark and against the page', (theme) => {
    for (const fill of ['--uaf-control', '--uaf-control-hover', '--uaf-control-pressed']) {
      expect(contrastRatio(colour(theme, '--uaf-surface'), colour(theme, fill)), fill).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(colour(theme, fill), colour(theme, '--uaf-page')), fill).toBeGreaterThanOrEqual(3)
    }
  })

  it.each(names)('%s: the focus ring stays visible on every surface and on the accent', (theme) => {
    for (const surface of surfaces) {
      expect(contrastRatio(colour(theme, '--uaf-focus'), colour(theme, surface)), surface).toBeGreaterThanOrEqual(3)
    }
  })

  it('uses no CSS variable that nothing defines', () => {
    const files = filesIn(SRC).filter((path) => /\.(vue|css)$/.test(path))
    const sources = files.map((path) => readFileSync(path, 'utf8'))
    const declared = new Set(sources.flatMap((source) => [...source.matchAll(/(--[\w-]+)'?\s*:/g)].map((match) => match[1])))
    const used = sources.flatMap((source) => [...source.matchAll(/var\((--[\w-]+)[,)]/g)].map((match) => match[1] ?? ''))
    const undefinedNames = [...new Set(used)].filter((name) => !declared.has(name) && !(name.slice(2) in THEMES.light))
    expect(used.length).toBeGreaterThan(0)
    expect(undefinedNames).toEqual([])
  })

  // WCAG 1.4.11: the icon on a node core is a meaningful mark, so it needs 3:1 against the core.
  it.each(FAMILY_NAMES)('family %s: the node icon meets 3:1 on its colour', (name) => {
    expect(contrastRatio(FAMILIES[name].ink, FAMILIES[name].color)).toBeGreaterThanOrEqual(3)
  })

  it('has no shadows in high contrast, where borders separate what floats', () => {
    expect(THEMES['high-contrast']['shadow-float']).toBe('none')
    expect(THEMES['high-contrast']['shadow-overlay']).toBe('none')
  })
})

describe('forced colours (Windows High Contrast)', () => {
  const source = (name: string) => readFileSync(join(SRC, 'components', name), 'utf8')

  it('draws checkbox and switch state in system colours, since the browser replaces backgrounds', () => {
    const toggle = source('ToggleControl.vue')
    expect(toggle).toContain('@media (forced-colors: active)')
    for (const colour of ['Highlight', 'HighlightText', 'ButtonText', 'Canvas']) expect(toggle).toContain(colour)
  })

  it('gives every button a visible edge', () => {
    expect(source('UButton.vue')).toMatch(/@media \(forced-colors: active\)[^@]*border-color: ButtonText/)
  })
})
