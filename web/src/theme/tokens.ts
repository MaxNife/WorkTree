// Design tokens: the single source of colour truth (docs/design-language.md).
// The objects use Fluent's own token names. theme/apply.ts writes them as CSS custom properties on
// the root, where the wrapped Fluent web components and styles/base.css both read them.

export type ThemeName = 'light' | 'dark' | 'high-contrast'
export type TokenValue = string | number
export type TokenSet = Record<string, TokenValue>

/** Accent: Fluent green (#107C10) and its tints. Change the brand here, nowhere else. */
export const BRAND = {
  base: '#107C10',
  hover: '#0E700E',
  pressed: '#0C5E0C',
  tint: '#DFF6DD',
  onDark: '#54B054',
  onDarkPressed: '#479647',
  linkOnDark: '#6CCB5F',
  linkHoverOnDark: '#8AD97D',
  tintOnDark: '#0A2E0A',
} as const

// Values that do not change with the theme (Fluent's scale).
const shared: TokenSet = {
  colorNeutralForeground1Static: '#242424',
  colorNeutralForegroundStaticInverted: '#ffffff',
  fontFamilyBase:
    "'Segoe UI', 'Segoe UI Web (West European)', -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', sans-serif",
  fontFamilyMonospace: "Consolas, 'Courier New', Courier, monospace",
  fontFamilyNumeric: "Bahnschrift, 'Segoe UI', sans-serif",
  fontSizeBase100: '10px',
  fontSizeBase200: '12px',
  fontSizeBase300: '14px',
  fontSizeBase400: '16px',
  fontSizeBase500: '20px',
  fontSizeBase600: '24px',
  fontSizeHero700: '28px',
  fontSizeHero800: '32px',
  fontSizeHero900: '40px',
  fontSizeHero1000: '68px',
  lineHeightBase100: '14px',
  lineHeightBase200: '16px',
  lineHeightBase300: '20px',
  lineHeightBase400: '22px',
  lineHeightBase500: '28px',
  lineHeightBase600: '32px',
  lineHeightHero700: '36px',
  lineHeightHero800: '40px',
  lineHeightHero900: '52px',
  lineHeightHero1000: '92px',
  fontWeightRegular: 400,
  fontWeightMedium: 500,
  fontWeightSemibold: 600,
  fontWeightBold: 700,
  borderRadiusNone: '0',
  borderRadiusSmall: '2px',
  borderRadiusMedium: '4px',
  borderRadiusLarge: '6px',
  borderRadiusXLarge: '8px',
  borderRadiusCircular: '10000px',
  strokeWidthThin: '1px',
  strokeWidthThick: '2px',
  strokeWidthThicker: '3px',
  strokeWidthThickest: '4px',
  spacingHorizontalNone: '0',
  spacingHorizontalXXS: '2px',
  spacingHorizontalXS: '4px',
  spacingHorizontalSNudge: '6px',
  spacingHorizontalS: '8px',
  spacingHorizontalMNudge: '10px',
  spacingHorizontalM: '12px',
  spacingHorizontalL: '16px',
  spacingHorizontalXL: '20px',
  spacingHorizontalXXL: '24px',
  spacingHorizontalXXXL: '32px',
  spacingVerticalNone: '0',
  spacingVerticalXXS: '2px',
  spacingVerticalXS: '4px',
  spacingVerticalSNudge: '6px',
  spacingVerticalS: '8px',
  spacingVerticalMNudge: '10px',
  spacingVerticalM: '12px',
  spacingVerticalL: '16px',
  spacingVerticalXL: '20px',
  spacingVerticalXXL: '24px',
  spacingVerticalXXXL: '32px',
  durationUltraFast: '50ms',
  durationFaster: '100ms',
  durationFast: '150ms',
  durationNormal: '200ms',
  durationSlow: '300ms',
  durationSlower: '400ms',
  durationUltraSlow: '500ms',
  durationGentle: '250ms',
  curveAccelerateMax: 'cubic-bezier(0.9,0.1,1,0.2)',
  curveAccelerateMid: 'cubic-bezier(1,0,1,1)',
  curveAccelerateMin: 'cubic-bezier(0.8,0,0.78,1)',
  curveDecelerateMax: 'cubic-bezier(0.1,0.9,0.2,1)',
  curveDecelerateMid: 'cubic-bezier(0,0,0,1)',
  curveDecelerateMin: 'cubic-bezier(0.33,0,0.1,1)',
  curveEasyEaseMax: 'cubic-bezier(0.8,0,0.2,1)',
  curveEasyEase: 'cubic-bezier(0.33,0,0.67,1)',
  curveLinear: 'cubic-bezier(0,0,1,1)',
}

interface Palette {
  fg1: string
  fg2: string
  fg3: string
  fg4: string
  fgDisabled: string
  fgOnBrand: string
  bg1: string
  bg1Hover: string
  bg1Pressed: string
  bg1Selected: string
  bg2: string
  bg3: string
  bg4: string
  bg5: string
  bg6: string
  bgDisabled: string
  subtleHover: string
  subtlePressed: string
  subtleSelected: string
  stroke1: string
  stroke1Hover: string
  stroke1Pressed: string
  stroke2: string
  stroke3: string
  strokeAccessible: string
  strokeDisabled: string
  focus1: string
  focus2: string
  overlay: string
  shadow: [string, string]
  brandBg: string
  brandBgHover: string
  brandBgPressed: string
  brandBg2: string
  // Fills under a small glyph (checkbox tick, switch thumb), which sits in the inverted foreground.
  compoundBg: string
  compoundBgHover: string
  compoundBgPressed: string
  brandFg: string
  brandFg2: string
  brandLink: string
  brandLinkHover: string
  brandStroke: string
  wordmarkWork: string
  wordmarkTree: string
  status: Record<'green' | 'red' | 'yellow' | 'orange', [fg: string, bg: string, border: string]>
}

function build(p: Palette): TokenSet {
  const t: TokenSet = { ...shared }
  const set = (names: string[], value: string) => names.forEach((n) => (t[n] = value))
  set(['colorNeutralForeground1', 'colorNeutralForeground1Hover', 'colorNeutralForeground1Pressed', 'colorNeutralForeground1Selected'], p.fg1)
  set(['colorNeutralForeground2', 'colorNeutralForeground2Hover', 'colorNeutralForeground2Pressed', 'colorNeutralForeground2Selected'], p.fg2)
  set(['colorNeutralForeground3', 'colorNeutralForeground3Hover', 'colorNeutralForeground3Pressed', 'colorNeutralForeground3Selected'], p.fg3)
  t.colorNeutralForeground4 = p.fg4
  t.colorNeutralForegroundDisabled = p.fgDisabled
  t.colorNeutralForegroundOnBrand = p.fgOnBrand
  set(['colorNeutralForegroundInverted', 'colorNeutralForegroundInvertedHover', 'colorNeutralForegroundInvertedPressed'], p.bg1)
  set(['colorNeutralForeground2BrandHover', 'colorNeutralForeground2BrandPressed', 'colorNeutralForeground2BrandSelected'], p.brandFg)
  set(['colorNeutralForeground3BrandHover', 'colorNeutralForeground3BrandPressed', 'colorNeutralForeground3BrandSelected'], p.brandFg)
  set(['colorBrandForeground1', 'colorCompoundBrandForeground1'], p.brandFg)
  t.colorCompoundBrandForeground1Hover = p.brandFg2
  t.colorCompoundBrandForeground1Pressed = p.brandFg2
  t.colorBrandForeground2 = p.brandFg2
  t.colorBrandForegroundLink = p.brandLink
  t.colorBrandForegroundLinkHover = p.brandLinkHover
  t.colorBrandForegroundLinkPressed = p.brandLinkHover
  t.colorBrandForegroundLinkSelected = p.brandLink
  t.colorNeutralForeground2Link = p.fg2
  t.colorNeutralForeground2LinkHover = p.fg1
  t.colorNeutralForeground2LinkPressed = p.fg1
  t.colorNeutralForeground2LinkSelected = p.fg1

  t.colorNeutralBackground1 = p.bg1
  t.colorNeutralBackground1Hover = p.bg1Hover
  t.colorNeutralBackground1Pressed = p.bg1Pressed
  t.colorNeutralBackground1Selected = p.bg1Selected
  for (const [i, v] of [p.bg2, p.bg3, p.bg4, p.bg5].entries()) {
    const n = i + 2
    t[`colorNeutralBackground${n}`] = v
    t[`colorNeutralBackground${n}Hover`] = p.bg1Hover
    t[`colorNeutralBackground${n}Pressed`] = p.bg1Pressed
    t[`colorNeutralBackground${n}Selected`] = p.bg1Selected
  }
  t.colorNeutralBackground6 = p.bg6
  t.colorNeutralBackgroundDisabled = p.bgDisabled
  t.colorNeutralBackgroundInverted = p.fg1
  t.colorSubtleBackground = 'transparent'
  t.colorSubtleBackgroundHover = p.subtleHover
  t.colorSubtleBackgroundPressed = p.subtlePressed
  t.colorSubtleBackgroundSelected = p.subtleSelected
  t.colorTransparentBackground = 'transparent'
  t.colorTransparentBackgroundHover = 'transparent'
  t.colorTransparentBackgroundPressed = 'transparent'
  t.colorTransparentBackgroundSelected = 'transparent'
  t.colorBackgroundOverlay = p.overlay

  t.colorBrandBackground = p.brandBg
  t.colorBrandBackgroundHover = p.brandBgHover
  t.colorBrandBackgroundPressed = p.brandBgPressed
  t.colorBrandBackgroundSelected = p.brandBgHover
  t.colorCompoundBrandBackground = p.compoundBg
  t.colorCompoundBrandBackgroundHover = p.compoundBgHover
  t.colorCompoundBrandBackgroundPressed = p.compoundBgPressed
  t.colorBrandBackground2 = p.brandBg2
  t.colorBrandBackgroundStatic = p.brandBg

  t.colorNeutralStroke1 = p.stroke1
  t.colorNeutralStroke1Hover = p.stroke1Hover
  t.colorNeutralStroke1Pressed = p.stroke1Pressed
  t.colorNeutralStroke1Selected = p.stroke1Pressed
  t.colorNeutralStroke2 = p.stroke2
  t.colorNeutralStroke3 = p.stroke3
  t.colorNeutralStrokeAccessible = p.strokeAccessible
  t.colorNeutralStrokeAccessibleHover = p.fg2
  t.colorNeutralStrokeAccessiblePressed = p.fg1
  t.colorNeutralStrokeAccessibleSelected = p.brandStroke
  t.colorNeutralStrokeDisabled = p.strokeDisabled
  t.colorNeutralStrokeOnBrand = p.focus1
  t.colorNeutralStrokeOnBrand2 = p.focus1
  t.colorBrandStroke1 = p.brandStroke
  t.colorBrandStroke2 = p.brandBg2
  t.colorCompoundBrandStroke = p.brandStroke
  t.colorCompoundBrandStrokeHover = p.compoundBgHover
  t.colorCompoundBrandStrokePressed = p.compoundBgPressed
  t.colorTransparentStroke = 'transparent'
  t.colorTransparentStrokeInteractive = 'transparent'
  t.colorTransparentStrokeDisabled = 'transparent'
  t.colorStrokeFocus1 = p.focus1
  t.colorStrokeFocus2 = p.focus2
  // WorkTree wordmark: "Work" in green, "Tree" in brown.
  t.wordmarkWork = p.wordmarkWork
  t.wordmarkTree = p.wordmarkTree

  for (const [name, [fg, bg, border]] of Object.entries(p.status)) {
    const key = { green: 'Green', red: 'Red', yellow: 'Yellow', orange: 'DarkOrange' }[name]
    t[`colorPalette${key}Foreground1`] = fg
    t[`colorPalette${key}Foreground2`] = fg
    t[`colorPalette${key}Foreground3`] = fg
    t[`colorPalette${key}Background1`] = bg
    t[`colorPalette${key}Background2`] = bg
    t[`colorPalette${key}Background3`] = border
    t[`colorPalette${key}Border1`] = border
    t[`colorPalette${key}Border2`] = border
    t[`colorPalette${key}BorderActive`] = fg
  }

  t.colorNeutralShadowAmbient = p.shadow[0]
  t.colorNeutralShadowKey = p.shadow[1]
  t.shadow2 = `0 0 2px ${p.shadow[0]}, 0 1px 2px ${p.shadow[1]}`
  t.shadow4 = `0 0 2px ${p.shadow[0]}, 0 2px 4px ${p.shadow[1]}`
  t.shadow8 = `0 0 2px ${p.shadow[0]}, 0 4px 8px ${p.shadow[1]}`
  t.shadow16 = `0 0 2px ${p.shadow[0]}, 0 8px 16px ${p.shadow[1]}`
  t.shadow28 = `0 0 8px ${p.shadow[0]}, 0 14px 28px ${p.shadow[1]}`
  t.shadow64 = `0 0 8px ${p.shadow[0]}, 0 32px 64px ${p.shadow[1]}`
  return t
}

const light: Palette = {
  fg1: '#242424', fg2: '#424242', fg3: '#616161', fg4: '#707070', fgDisabled: '#bdbdbd', fgOnBrand: '#ffffff',
  bg1: '#ffffff', bg1Hover: '#f5f5f5', bg1Pressed: '#e0e0e0', bg1Selected: '#ebebeb',
  bg2: '#fafafa', bg3: '#f5f5f5', bg4: '#f0f0f0', bg5: '#ebebeb', bg6: '#e6e6e6', bgDisabled: '#f0f0f0',
  subtleHover: '#f5f5f5', subtlePressed: '#e0e0e0', subtleSelected: '#ebebeb',
  stroke1: '#d1d1d1', stroke1Hover: '#c7c7c7', stroke1Pressed: '#b3b3b3', stroke2: '#e0e0e0', stroke3: '#f0f0f0',
  strokeAccessible: '#616161', strokeDisabled: '#e0e0e0', focus1: '#ffffff', focus2: '#000000',
  overlay: 'rgba(0,0,0,0.4)', shadow: ['rgba(0,0,0,0.12)', 'rgba(0,0,0,0.14)'],
  brandBg: BRAND.base, brandBgHover: BRAND.hover, brandBgPressed: BRAND.pressed, brandBg2: BRAND.tint,
  compoundBg: BRAND.base, compoundBgHover: BRAND.hover, compoundBgPressed: BRAND.pressed,
  brandFg: BRAND.base, brandFg2: BRAND.pressed, brandLink: BRAND.hover, brandLinkHover: BRAND.pressed, brandStroke: BRAND.base,
  wordmarkWork: BRAND.base, wordmarkTree: '#7a4a1e',
  status: {
    green: ['#107c10', '#f1faf1', '#9fd89f'],
    red: ['#b10e1c', '#fdf3f4', '#eeacb2'],
    yellow: ['#835b00', '#fff9e5', '#fde300'],
    orange: ['#bc4b09', '#fdf6f3', '#f4bfab'],
  },
}

const dark: Palette = {
  fg1: '#ffffff', fg2: '#d6d6d6', fg3: '#adadad', fg4: '#999999', fgDisabled: '#5c5c5c', fgOnBrand: '#ffffff',
  bg1: '#292929', bg1Hover: '#3d3d3d', bg1Pressed: '#1f1f1f', bg1Selected: '#333333',
  bg2: '#1f1f1f', bg3: '#141414', bg4: '#0f0f0f', bg5: '#0a0a0a', bg6: '#313131', bgDisabled: '#141414',
  subtleHover: '#383838', subtlePressed: '#2e2e2e', subtleSelected: '#333333',
  stroke1: '#666666', stroke1Hover: '#757575', stroke1Pressed: '#6b6b6b', stroke2: '#525252', stroke3: '#3d3d3d',
  strokeAccessible: '#d6d6d6', strokeDisabled: '#424242', focus1: '#000000', focus2: '#ffffff',
  overlay: 'rgba(0,0,0,0.5)', shadow: ['rgba(0,0,0,0.24)', 'rgba(0,0,0,0.28)'],
  brandBg: BRAND.base, brandBgHover: BRAND.hover, brandBgPressed: BRAND.pressed, brandBg2: BRAND.tintOnDark,
  compoundBg: BRAND.onDark, compoundBgHover: BRAND.linkOnDark, compoundBgPressed: BRAND.onDarkPressed,
  brandFg: BRAND.onDark, brandFg2: BRAND.linkOnDark, brandLink: BRAND.linkOnDark, brandLinkHover: BRAND.linkHoverOnDark, brandStroke: BRAND.onDark,
  wordmarkWork: BRAND.onDark, wordmarkTree: '#c9a27c',
  status: {
    green: ['#9fd89f', '#052505', '#107c10'],
    red: ['#eeacb2', '#3b0509', '#b10e1c'],
    yellow: ['#fde300', '#3d2e00', '#835b00'],
    orange: ['#f4bfab', '#411200', '#bc4b09'],
  },
}

// High contrast: pure black and white with yellow for brand and a cyan focus ring.
const highContrast: Palette = {
  fg1: '#ffffff', fg2: '#ffffff', fg3: '#ffffff', fg4: '#ffffff', fgDisabled: '#a6a6a6', fgOnBrand: '#000000',
  bg1: '#000000', bg1Hover: '#1a1a1a', bg1Pressed: '#333333', bg1Selected: '#1a1a1a',
  bg2: '#000000', bg3: '#000000', bg4: '#000000', bg5: '#000000', bg6: '#000000', bgDisabled: '#000000',
  subtleHover: '#1a1a1a', subtlePressed: '#333333', subtleSelected: '#1a1a1a',
  stroke1: '#ffffff', stroke1Hover: '#ffff00', stroke1Pressed: '#ffff00', stroke2: '#ffffff', stroke3: '#ffffff',
  strokeAccessible: '#ffffff', strokeDisabled: '#a6a6a6', focus1: '#000000', focus2: '#00ffff',
  overlay: 'rgba(0,0,0,0.8)', shadow: ['rgba(255,255,255,0)', 'rgba(255,255,255,0)'],
  brandBg: '#ffff00', brandBgHover: '#ffffff', brandBgPressed: '#ffffff', brandBg2: '#000000',
  compoundBg: '#ffff00', compoundBgHover: '#ffffff', compoundBgPressed: '#ffffff',
  brandFg: '#ffff00', brandFg2: '#ffff00', brandLink: '#ffff00', brandLinkHover: '#ffffff', brandStroke: '#ffff00',
  wordmarkWork: '#3ff23f', wordmarkTree: '#ffa94d',
  status: {
    green: ['#3ff23f', '#000000', '#3ff23f'],
    red: ['#ff6b6b', '#000000', '#ff6b6b'],
    yellow: ['#ffff00', '#000000', '#ffff00'],
    orange: ['#ffa94d', '#000000', '#ffa94d'],
  },
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
