import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import { applyTheme, resolveTheme } from '@/theme/apply'
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
  const match = new RegExp(`${variable}: var\\(--(\\w+)\\)`).exec(baseCss)
  if (!match?.[1]) throw new Error(`${variable} is not mapped in base.css`)
  return match[1]
}

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

  // Everything a status dot can be painted with, read from the component so a remap is caught.
  const badge = readFileSync(join(SRC, 'components', 'StatusBadge.vue'), 'utf8')
  const dots = [...badge.matchAll(/--dot: var\((--uaf-[\w-]+)\)/g)].map((match) => tokenBehind(match[1] ?? ''))

  it('finds a colour for every status kind', () => {
    expect(dots).toHaveLength(6)
  })

  // WCAG 1.4.11: 3:1 for a meaningful mark against what is next to it.
  it.each(names)('%s: every status dot meets 3:1 on the page and on sunken panels', (theme) => {
    const tokens = THEMES[theme]
    for (const dot of dots) {
      for (const surface of ['colorNeutralBackground1', 'colorNeutralBackground3']) {
        expect(contrastRatio(String(tokens[dot]), String(tokens[surface])), `${dot} on ${surface}`).toBeGreaterThanOrEqual(3)
      }
    }
  })

  it.each(names)('%s: error and muted text meet 4.5:1 on the page and on sunken panels', (theme) => {
    const tokens = THEMES[theme]
    for (const text of [tokenBehind('--uaf-danger'), tokenBehind('--uaf-text-muted')]) {
      for (const surface of ['colorNeutralBackground1', 'colorNeutralBackground3']) {
        expect(contrastRatio(String(tokens[text]), String(tokens[surface])), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  // The tick of a checkbox and the thumb of a switch sit in the inverted foreground on these fills.
  const fills = ['colorCompoundBrandBackground', 'colorCompoundBrandBackgroundHover', 'colorCompoundBrandBackgroundPressed']
  it.each(names)('%s: a checked checkbox or switch keeps 3:1 for its mark and against the page', (theme) => {
    const tokens = THEMES[theme]
    for (const fill of fills) {
      expect(contrastRatio(String(tokens.colorNeutralForegroundInverted), String(tokens[fill])), fill).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(String(tokens[fill]), String(tokens.colorNeutralBackground1)), fill).toBeGreaterThanOrEqual(3)
    }
  })

  it('defines every token the registered Fluent components read', () => {
    const fluent = join(WEB, 'node_modules', '@fluentui', 'web-components', 'dist', 'esm')
    const registered = [...readFileSync(join(SRC, 'fluent.ts'), 'utf8').matchAll(/web-components\/([\w-]+)\/define\.js/g)].map(
      (match) => match[1] ?? '',
    )
    expect(registered.length).toBeGreaterThan(0)
    const sources = [
      ...registered.map((name) => join(fluent, name, `${name}.styles.js`)),
      ...filesIn(join(fluent, 'styles')).filter((path) => path.endsWith('.js')),
    ]
    const used = sources.flatMap((path) =>
      [...readFileSync(path, 'utf8').matchAll(/import \{([^}]*)\} from '[./]*theme\/design-tokens\.js'/g)].flatMap((match) =>
        (match[1] ?? '').split(',').map((name) => name.trim()).filter(Boolean),
      ),
    )
    expect(used.length).toBeGreaterThan(0)
    expect(used.filter((name) => !(name in THEMES.light))).toEqual([])
  })

  it('uses no CSS variable that nothing defines', () => {
    // Fluent sets these two on its own textarea host; UTextArea sizes itself with them.
    const fluentHostVariables = ['--line-height', '--padding-block']
    const files = filesIn(SRC).filter((path) => /\.(vue|css)$/.test(path))
    const sources = files.map((path) => readFileSync(path, 'utf8'))
    const declared = new Set(sources.flatMap((source) => [...source.matchAll(/(--[\w-]+)'?\s*:/g)].map((match) => match[1])))
    const used = sources.flatMap((source) => [...source.matchAll(/var\((--[\w-]+)[,)]/g)].map((match) => match[1] ?? ''))
    const undefinedNames = [...new Set(used)].filter(
      (name) => !declared.has(name) && !(name.slice(2) in THEMES.light) && !fluentHostVariables.includes(name),
    )
    expect(used.length).toBeGreaterThan(0)
    expect(undefinedNames).toEqual([])
  })

  it('leaves the focus ring of each Fluent control to Fluent, so none gets two', () => {
    const ring = /:focus-visible:not\(([^{]*)\)\s*\{/.exec(baseCss)?.[1] ?? ''
    for (const control of ['fluent-button', 'fluent-checkbox', 'fluent-switch', 'fluent-text-input', 'fluent-textarea', 'fluent-dropdown [role=']) {
      expect(ring).toContain(control)
    }
  })

  it('cuts every duration token for reduced motion, which is how the rule reaches Fluent', () => {
    const durations = Object.keys(THEMES.light).filter((name) => name.startsWith('duration'))
    expect(durations.length).toBeGreaterThan(0)
    for (const name of durations) expect(baseCss).toMatch(new RegExp(`--${name}: [^;]+!important`))
  })

  it('keeps the focus ring visible against the page in every theme', () => {
    for (const theme of names) {
      expect(contrastRatio(String(THEMES[theme].colorStrokeFocus2), String(THEMES[theme].colorNeutralBackground1))).toBeGreaterThanOrEqual(3)
    }
  })
})
