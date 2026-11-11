// Design tokens: the single source of colour truth (docs/04-ui-reimplementation-guide.md).
// theme/apply.ts writes them as CSS custom properties on the root, and styles/base.css maps them to
// the --uaf-* variables components use. A token name here is its CSS name without the leading dashes.

export type ThemeName = 'light' | 'dark' | 'high-contrast'
export type TokenValue = string | number
export type TokenSet = Record<string, TokenValue>

/** Accent: WorkTree green and its tints. Change the brand here, nowhere else. */
export const BRAND = {
  base: '#107C10',
  hover: '#0E700E',
  pressed: '#0C5E0C',
  tint: '#E2F0DD',
  onDark: '#5DB65A',
  onDarkPressed: '#4B9A49',
  linkOnDark: '#7BCB72',
  linkHoverOnDark: '#9ADB92',
  tintOnDark: '#20331D',
} as const

// Values that do not change with the theme.
const shared: TokenSet = {
  'font-family-base':
    "'Segoe UI Variable Text', 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', sans-serif",
  'font-family-mono': "'Cascadia Mono', Consolas, 'Courier New', Courier, monospace",
  'font-size-10': '10px',
  'font-size-12': '12px',
  'font-size-14': '14px',
  'font-size-16': '16px',
  'font-size-20': '20px',
  'font-size-24': '24px',
  'font-size-28': '28px',
  'line-height-14': '14px',
  'line-height-16': '16px',
  'line-height-20': '20px',
  'line-height-22': '22px',
  'line-height-28': '28px',
  'line-height-32': '32px',
  'line-height-36': '36px',
  'weight-regular': 400,
  'weight-medium': 500,
  'weight-semibold': 600,
  'weight-bold': 700,
  // Soft but not uniform: containers are rounder than the controls inside them.
  'radius-control': '8px',
  'radius-container': '12px',
  'radius-full': '999px',
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
  'duration-fast': '100ms',
  'duration-normal': '200ms',
  'duration-slow': '500ms',
  'ease-standard': 'cubic-bezier(0.33,0,0.67,1)',
}

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
  overlay: string
  accent: string
  accentHover: string
  accentPressed: string
  accentTint: string
  accentText: string
  // Fills under a small glyph (checkbox tick, switch thumb), which sits in the surface colour.
  control: string
  controlHover: string
  controlPressed: string
  link: string
  linkHover: string
  wordmarkWork: string
  wordmarkTree: string
  status: Record<'ok' | 'danger' | 'warn' | 'attention', [fg: string, bg: string, border: string]>
  /** Soft lift for what floats above the page: menus, popovers, toasts and dialogs. */
  shadowFloat: string
  shadowOverlay: string
}

const light: Palette = {
  text: '#26231F', textSecondary: '#46413A', textMuted: '#5F584E', textDisabled: '#A9A297', textOnAccent: '#ffffff',
  page: '#F8F6F2', surface: '#ffffff', sunken: '#F2EEE8', hover: '#F3EFE9', pressed: '#E8E2D9', selected: '#EAE5DC', disabledFill: '#F0ECE5',
  border: '#E6E0D6', borderStrong: '#D2CABD', borderControl: '#8C8478',
  focus: '#000000', overlay: 'rgba(38,35,31,0.42)',
  accent: BRAND.base, accentHover: BRAND.hover, accentPressed: BRAND.pressed, accentTint: BRAND.tint, accentText: BRAND.base,
  control: BRAND.base, controlHover: BRAND.hover, controlPressed: BRAND.pressed,
  link: BRAND.hover, linkHover: BRAND.pressed,
  wordmarkWork: BRAND.base, wordmarkTree: '#7a4a1e',
  status: {
    ok: ['#0F6F1A', '#EEF7EC', '#A9D6A3'],
    danger: ['#AE1B23', '#FCF1EF', '#EBB2AE'],
    warn: ['#7D5700', '#FDF6E3', '#E7C565'],
    attention: ['#B24A0C', '#FCF3EC', '#F0C0A0'],
  },
  shadowFloat: '0 1px 2px rgba(61,50,35,0.08), 0 6px 18px rgba(61,50,35,0.10)',
  shadowOverlay: '0 2px 4px rgba(61,50,35,0.10), 0 16px 40px rgba(61,50,35,0.18)',
}

const dark: Palette = {
  text: '#F6F2EC', textSecondary: '#DAD3C9', textMuted: '#B9B1A5', textDisabled: '#6F685E', textOnAccent: '#ffffff',
  page: '#1C1A17', surface: '#262320', sunken: '#171512', hover: '#332F2B', pressed: '#211E1B', selected: '#3A3631', disabledFill: '#2A2723',
  border: '#3E3933', borderStrong: '#5A534A', borderControl: '#8E867A',
  focus: '#ffffff', overlay: 'rgba(0,0,0,0.55)',
  accent: BRAND.base, accentHover: BRAND.hover, accentPressed: BRAND.pressed, accentTint: BRAND.tintOnDark, accentText: BRAND.onDark,
  control: BRAND.onDark, controlHover: BRAND.linkOnDark, controlPressed: BRAND.onDarkPressed,
  link: BRAND.linkOnDark, linkHover: BRAND.linkHoverOnDark,
  wordmarkWork: BRAND.onDark, wordmarkTree: '#c9a27c',
  status: {
    ok: ['#9FD89A', '#14290F', '#3E7A38'],
    danger: ['#F0AFA9', '#3A1412', '#9C2F2A'],
    warn: ['#EFCB6A', '#332708', '#7D5F12'],
    attention: ['#F2BE9E', '#3A1E0E', '#A2542A'],
  },
  shadowFloat: '0 1px 2px rgba(0,0,0,0.30), 0 6px 18px rgba(0,0,0,0.34)',
  shadowOverlay: '0 2px 4px rgba(0,0,0,0.34), 0 16px 40px rgba(0,0,0,0.46)',
}

// High contrast: pure black and white with yellow for the accent and a cyan focus ring. No shadows:
// the white borders already separate what floats.
const highContrast: Palette = {
  text: '#ffffff', textSecondary: '#ffffff', textMuted: '#ffffff', textDisabled: '#a6a6a6', textOnAccent: '#000000',
  page: '#000000', surface: '#000000', sunken: '#000000', hover: '#1a1a1a', pressed: '#333333', selected: '#1a1a1a', disabledFill: '#000000',
  border: '#ffffff', borderStrong: '#ffffff', borderControl: '#ffffff',
  focus: '#00ffff', overlay: 'rgba(0,0,0,0.8)',
  accent: '#ffff00', accentHover: '#ffffff', accentPressed: '#ffffff', accentTint: '#000000', accentText: '#ffff00',
  control: '#ffff00', controlHover: '#ffffff', controlPressed: '#ffffff',
  link: '#ffff00', linkHover: '#ffffff',
  wordmarkWork: '#3ff23f', wordmarkTree: '#ffa94d',
  status: {
    ok: ['#3ff23f', '#000000', '#3ff23f'],
    danger: ['#ff6b6b', '#000000', '#ff6b6b'],
    warn: ['#ffff00', '#000000', '#ffff00'],
    attention: ['#ffa94d', '#000000', '#ffa94d'],
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
    'color-overlay': p.overlay,
    'color-accent': p.accent,
    'color-accent-hover': p.accentHover,
    'color-accent-pressed': p.accentPressed,
    'color-accent-tint': p.accentTint,
    'color-accent-text': p.accentText,
    'color-control': p.control,
    'color-control-hover': p.controlHover,
    'color-control-pressed': p.controlPressed,
    'color-link': p.link,
    'color-link-hover': p.linkHover,
    'wordmark-work': p.wordmarkWork,
    'wordmark-tree': p.wordmarkTree,
    'shadow-float': p.shadowFloat,
    'shadow-overlay': p.shadowOverlay,
  }
  for (const [name, [fg, bg, border]] of Object.entries(p.status)) {
    t[`color-${name}`] = fg
    t[`color-${name}-bg`] = bg
    t[`color-${name}-border`] = border
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
