// Design tokens: the single source of colour truth (docs/04-ui-reimplementation-guide.md, section 3).
// theme/apply.ts writes them as CSS custom properties on the root, and styles/base.css maps them to
// the --wt-* variables components use. A token name here is its CSS name without the leading dashes.

export type ThemeName = 'light' | 'dark' | 'high-contrast'
export type TokenValue = string | number
export type TokenSet = Record<string, TokenValue>

export type FlowerName = 'hibiscus' | 'marigold' | 'fern' | 'lagoon' | 'morning-glory' | 'iris' | 'orchid'

export interface Flower {
  label: string
  /** The colour itself: fills, petals, dots. */
  strong: string
  /** A tint for fills behind text. */
  soft: string
  /** Text and icons on the soft tint. */
  deep: string
  /** Text on the strong colour. Only bold text and icons: body text uses deep on soft. */
  on: string
}

/** The seven flowers. Change the palette here, nowhere else. */
export const FLOWERS: Record<FlowerName, Flower> = {
  hibiscus: { label: 'Hibiscus', strong: '#EE3F3A', soft: '#FFE7E3', deep: '#B3211D', on: '#ffffff' },
  marigold: { label: 'Marigold', strong: '#FFB01F', soft: '#FFF1CF', deep: '#7A4E00', on: '#231F2E' },
  fern: { label: 'Fern', strong: '#0E9F5B', soft: '#DDF6E6', deep: '#0A6B3D', on: '#ffffff' },
  lagoon: { label: 'Lagoon', strong: '#0AA5B8', soft: '#D9F4F7', deep: '#06707D', on: '#231F2E' },
  'morning-glory': { label: 'Morning glory', strong: '#2A7BEA', soft: '#DFEBFE', deep: '#1553B0', on: '#ffffff' },
  iris: { label: 'Iris', strong: '#6246EA', soft: '#E8E3FF', deep: '#3A2A9E', on: '#ffffff' },
  orchid: { label: 'Orchid', strong: '#E0288F', soft: '#FFE1F1', deep: '#9C1561', on: '#ffffff' },
}

export const FLOWER_NAMES = Object.keys(FLOWERS) as FlowerName[]

/** Night soil: the ink of the product, and the strongest button on a coloured band. */
export const NIGHT_SOIL = '#231F2E'

// Values that do not change with the theme.
const shared: TokenSet = {
  'font-family-base':
    "'Segoe UI Variable Text', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'SF Pro Text', Roboto, 'Helvetica Neue', Arial, sans-serif",
  'font-family-head':
    "'Segoe UI Variable Display', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'SF Pro Display', Roboto, 'Helvetica Neue', Arial, sans-serif",
  'font-family-mono': "'Cascadia Mono', Consolas, 'SF Mono', Menlo, 'Roboto Mono', monospace",
  'font-size-10': '10px',
  'font-size-11': '11px',
  'font-size-12': '12px',
  'font-size-14': '14px',
  'font-size-16': '16px',
  'font-size-20': '20px',
  'font-size-24': '24px',
  'font-size-28': '28px',
  'font-size-30': '30px',
  'line-height-14': '14px',
  'line-height-16': '16px',
  'line-height-20': '20px',
  'line-height-22': '22px',
  'line-height-28': '28px',
  'line-height-30': '30px',
  'line-height-32': '32px',
  'line-height-34': '34px',
  'line-height-36': '36px',
  'weight-regular': 400,
  'weight-medium': 500,
  'weight-semibold': 600,
  'weight-bold': 700,
  'tracking-head': '-0.02em',
  // Soft, generous corners: controls, then cards and tables, then the app frame and dialogs.
  'radius-control': '10px',
  'radius-container': '16px',
  'radius-frame': '20px',
  'radius-full': '999px',
  // The leaf: WorkTree's own corner. The gentler one is for stat tiles and swatches.
  'radius-leaf': '3px 60% 3px 60%',
  'radius-leaf-soft': '16px 16px 16px 4px',
  'stroke-1': '1px',
  'stroke-2': '2px',
  'stroke-3': '3px',
  'stroke-4': '4px',
  'space-0': '0',
  'space-2': '2px',
  'space-4': '4px',
  'space-6': '6px',
  'space-8': '8px',
  'space-10': '10px',
  'space-12': '12px',
  'space-16': '16px',
  'space-20': '20px',
  'space-24': '24px',
  'space-32': '32px',
  'space-48': '48px',
  // Motion explains cause and effect; it is never a wait (section 3.4).
  'motion-instant': '80ms',
  'motion-quick': '140ms',
  'motion-move': '220ms',
  'motion-grow': '420ms',
  'ease-out': 'cubic-bezier(0, 0, 0.2, 1)',
  'ease-move': 'cubic-bezier(0.2, 0, 0, 1)',
  'ease-grow': 'cubic-bezier(0.3, 0, 0.1, 1)',
  // Older names kept for the components that already use them.
  'duration-fast': '80ms',
  'duration-normal': '140ms',
  'duration-slow': '420ms',
  'ease-standard': 'cubic-bezier(0, 0, 0.2, 1)',
}

type Status = [fg: string, bg: string, border: string]

interface Palette {
  text: string
  textSecondary: string
  textMuted: string
  textDisabled: string
  textOnAccent: string
  page: string
  surface: string
  sunken: string
  hover: string
  pressed: string
  selected: string
  disabledFill: string
  border: string
  borderStrong: string
  borderControl: string
  focus: string
  /** The gap between the focus ring and what it surrounds. */
  focusGap: string
  overlay: string
  accent: string
  accentHover: string
  accentPressed: string
  accentTint: string
  accentText: string
  /** The single strongest action on a coloured band. */
  strong: string
  strongHover: string
  onStrong: string
  /** Destructive actions. White text needs the deep value: on the strong one it reaches only 3.9:1. */
  destructive: string
  destructiveHover: string
  onDestructive: string
  // Fills under a small glyph (checkbox tick, switch thumb), which sits in the surface colour.
  control: string
  controlHover: string
  controlPressed: string
  link: string
  linkHover: string
  /** Per flower: [strong, soft, deep] in this theme. */
  flowers: Record<FlowerName, [strong: string, soft: string, deep: string]>
  status: Record<'ok' | 'danger' | 'warn' | 'attention' | 'running', Status>
  /** Soft lift for what floats above the page: menus, popovers, toasts and dialogs. */
  shadowFloat: string
  shadowOverlay: string
}

const lightFlowers = Object.fromEntries(
  FLOWER_NAMES.map((name) => [name, [FLOWERS[name].strong, FLOWERS[name].soft, FLOWERS[name].deep]]),
) as Palette['flowers']

const statusFrom = (flowers: Palette['flowers'], name: FlowerName): Status => {
  const [strong, soft, deep] = flowers[name]
  return [deep, soft, strong]
}

const light: Palette = {
  text: NIGHT_SOIL, textSecondary: '#433C52', textMuted: '#5E5670', textDisabled: '#A59DB4', textOnAccent: '#ffffff',
  page: '#FBFAFE', surface: '#ffffff', sunken: '#F4F1FA', hover: '#F7F5FC', pressed: '#ECE7F5', selected: '#F4F1FA', disabledFill: '#F4F1FA',
  // Hairlines are faint by design; the edge of a field uses its own value, which reaches 3:1.
  border: '#E7E2F0', borderStrong: '#CFC8DC', borderControl: '#857C99',
  focus: NIGHT_SOIL, focusGap: '#ffffff', overlay: 'rgba(35,31,46,0.42)',
  accent: FLOWERS.iris.strong, accentHover: '#5136D6', accentPressed: '#4127C0', accentTint: FLOWERS.iris.soft, accentText: FLOWERS.iris.strong,
  strong: NIGHT_SOIL, strongHover: '#3A3448', onStrong: '#ffffff',
  destructive: FLOWERS.hibiscus.deep, destructiveHover: '#9A1A17', onDestructive: '#ffffff',
  control: FLOWERS.iris.strong, controlHover: '#5136D6', controlPressed: '#4127C0',
  link: '#5136D6', linkHover: FLOWERS.iris.deep,
  flowers: lightFlowers,
  status: {
    ok: statusFrom(lightFlowers, 'fern'),
    danger: statusFrom(lightFlowers, 'hibiscus'),
    warn: statusFrom(lightFlowers, 'marigold'),
    attention: statusFrom(lightFlowers, 'orchid'),
    running: statusFrom(lightFlowers, 'morning-glory'),
  },
  shadowFloat: '0 2px 4px rgba(35,31,46,0.06), 0 10px 28px rgba(35,31,46,0.12)',
  shadowOverlay: '0 2px 4px rgba(35,31,46,0.08), 0 16px 40px rgba(35,31,46,0.18)',
}

// Dark (proposed in the guide, not yet reviewed by the owner): the strong colours stay; the soft
// tints are 18 percent of the strong colour over the surface; the deep values become light tints.
const darkFlowers: Palette['flowers'] = {
  hibiscus: [FLOWERS.hibiscus.strong, '#46232E', '#FF9C96'],
  marigold: [FLOWERS.marigold.strong, '#493729', '#FFC657'],
  fern: [FLOWERS.fern.strong, '#1E3434', '#4FC48A'],
  lagoon: [FLOWERS.lagoon.strong, '#1D3544', '#3CC3D3'],
  'morning-glory': [FLOWERS['morning-glory'].strong, '#232E4D', '#7DB0F4'],
  iris: [FLOWERS.iris.strong, '#2D244D', '#B4A8FF'],
  orchid: [FLOWERS.orchid.strong, '#431F3D', '#F08CC4'],
}

const dark: Palette = {
  text: '#F5F2FB', textSecondary: '#D9D3E6', textMuted: '#B7AFC8', textDisabled: '#6E6782', textOnAccent: '#ffffff',
  page: '#17141F', surface: '#211D2B', sunken: '#131019', hover: '#2A2537', pressed: '#1B1724', selected: '#2D2840', disabledFill: '#1E1A27',
  border: '#35304A', borderStrong: '#4A4462', borderControl: '#7D7592',
  focus: '#F5F2FB', focusGap: '#17141F', overlay: 'rgba(0,0,0,0.55)',
  accent: FLOWERS.iris.strong, accentHover: '#5136D6', accentPressed: '#4127C0', accentTint: darkFlowers.iris[1], accentText: darkFlowers.iris[2],
  strong: '#F5F2FB', strongHover: '#FFFFFF', onStrong: NIGHT_SOIL,
  destructive: FLOWERS.hibiscus.deep, destructiveHover: '#9A1A17', onDestructive: '#ffffff',
  control: darkFlowers.iris[2], controlHover: '#C6BDFF', controlPressed: '#9683F1',
  link: darkFlowers.iris[2], linkHover: '#C6BDFF',
  flowers: darkFlowers,
  status: {
    ok: statusFrom(darkFlowers, 'fern'),
    danger: statusFrom(darkFlowers, 'hibiscus'),
    warn: statusFrom(darkFlowers, 'marigold'),
    attention: statusFrom(darkFlowers, 'orchid'),
    running: statusFrom(darkFlowers, 'morning-glory'),
  },
  shadowFloat: '0 2px 4px rgba(0,0,0,0.30), 0 10px 28px rgba(0,0,0,0.40)',
  shadowOverlay: '0 2px 4px rgba(0,0,0,0.34), 0 16px 40px rgba(0,0,0,0.50)',
}

// High contrast: black and white. A flower keeps its colour only where it passes on black; Iris does
// not, so it becomes white. No tints and no shadows: the white borders separate what floats.
const hcFlower = (name: FlowerName): [string, string, string] => {
  const colour = name === 'iris' ? '#ffffff' : FLOWERS[name].strong
  return [colour, '#000000', colour]
}
const hcFlowers = Object.fromEntries(FLOWER_NAMES.map((name) => [name, hcFlower(name)])) as Palette['flowers']

const highContrast: Palette = {
  text: '#ffffff', textSecondary: '#ffffff', textMuted: '#ffffff', textDisabled: '#a6a6a6', textOnAccent: '#000000',
  page: '#000000', surface: '#000000', sunken: '#000000', hover: '#1a1a1a', pressed: '#333333', selected: '#1a1a1a', disabledFill: '#000000',
  border: '#ffffff', borderStrong: '#ffffff', borderControl: '#ffffff',
  focus: '#00ffff', focusGap: '#000000', overlay: 'rgba(0,0,0,0.8)',
  accent: FLOWERS.marigold.strong, accentHover: '#ffffff', accentPressed: '#ffffff', accentTint: '#000000', accentText: FLOWERS.marigold.strong,
  strong: '#ffffff', strongHover: FLOWERS.marigold.strong, onStrong: '#000000',
  destructive: '#ff6b6b', destructiveHover: '#ffffff', onDestructive: '#000000',
  control: FLOWERS.marigold.strong, controlHover: '#ffffff', controlPressed: '#ffffff',
  link: FLOWERS.marigold.strong, linkHover: '#ffffff',
  flowers: hcFlowers,
  status: {
    ok: ['#3ff23f', '#000000', '#3ff23f'],
    danger: ['#ff6b6b', '#000000', '#ff6b6b'],
    warn: ['#ffff00', '#000000', '#ffff00'],
    attention: ['#ff8fd0', '#000000', '#ff8fd0'],
    running: ['#7DB0F4', '#000000', '#7DB0F4'],
  },
  shadowFloat: 'none',
  shadowOverlay: 'none',
}

function build(p: Palette): TokenSet {
  const t: TokenSet = {
    ...shared,
    'color-text': p.text,
    'color-text-secondary': p.textSecondary,
    'color-text-muted': p.textMuted,
    'color-text-disabled': p.textDisabled,
    'color-text-on-accent': p.textOnAccent,
    'color-page': p.page,
    'color-surface': p.surface,
    'color-surface-sunken': p.sunken,
    'color-surface-hover': p.hover,
    'color-surface-pressed': p.pressed,
    'color-surface-selected': p.selected,
    'color-surface-disabled': p.disabledFill,
    'color-border': p.border,
    'color-border-strong': p.borderStrong,
    'color-border-control': p.borderControl,
    'color-focus': p.focus,
    'color-focus-gap': p.focusGap,
    'color-overlay': p.overlay,
    'color-accent': p.accent,
    'color-accent-hover': p.accentHover,
    'color-accent-pressed': p.accentPressed,
    'color-accent-tint': p.accentTint,
    'color-accent-text': p.accentText,
    'color-strong': p.strong,
    'color-strong-hover': p.strongHover,
    'color-on-strong': p.onStrong,
    'color-destructive': p.destructive,
    'color-destructive-hover': p.destructiveHover,
    'color-on-destructive': p.onDestructive,
    'color-control': p.control,
    'color-control-hover': p.controlHover,
    'color-control-pressed': p.controlPressed,
    'color-link': p.link,
    'color-link-hover': p.linkHover,
    'shadow-float': p.shadowFloat,
    'shadow-overlay': p.shadowOverlay,
  }
  for (const [name, [fg, bg, border]] of Object.entries(p.status)) {
    t[`color-${name}`] = fg
    t[`color-${name}-bg`] = bg
    t[`color-${name}-border`] = border
  }
  // Flowers are written straight under their --wt-* names: --wt-iris, --wt-iris-soft, --wt-iris-deep.
  for (const [name, [strong, soft, deep]] of Object.entries(p.flowers)) {
    t[`wt-${name}`] = strong
    t[`wt-${name}-soft`] = soft
    t[`wt-${name}-deep`] = deep
  }
  return t
}

export const THEMES: Record<ThemeName, TokenSet> = {
  light: build(light),
  dark: build(dark),
  'high-contrast': build(highContrast),
}

export const THEME_LABELS: Record<ThemeName, string> = {
  light: 'Light',
  dark: 'Dark',
  'high-contrast': 'High contrast',
}

/** Relative luminance contrast ratio of two #rrggbb colours (WCAG 2.x). */
export function contrastRatio(a: string, b: string): number {
  const lum = (hex: string) => {
    const n = Number.parseInt(hex.slice(1), 16)
    const channel = (v: number) => {
      const s = v / 255
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
  }
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}
