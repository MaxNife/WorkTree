import { THEMES, type ThemeName, type TokenSet } from './tokens'

export const THEME_MODES = ['system', 'light', 'dark', 'high-contrast'] as const
export const DENSITIES = ['compact', 'comfortable'] as const

export type ThemeMode = (typeof THEME_MODES)[number]
export type Density = (typeof DENSITIES)[number]

/** Resolve the effective theme from the user's mode and the OS preferences. */
export function resolveTheme(
  mode: ThemeMode,
  media: (query: string) => boolean = (q) =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(q).matches,
): ThemeName {
  if (mode !== 'system') return mode
  if (media('(forced-colors: active)') || media('(prefers-contrast: more)')) return 'high-contrast'
  return media('(prefers-color-scheme: dark)') ? 'dark' : 'light'
}

/** Write the tokens as CSS custom properties (`--<name>`) so every stylesheet can read them. */
export function writeTokens(tokens: TokenSet, element: HTMLElement): void {
  for (const [name, value] of Object.entries(tokens)) element.style.setProperty(`--${name}`, String(value))
}

/** Apply a theme and density to the document. Components read them through styles/base.css. */
export function applyTheme(theme: ThemeName, density: Density, root: HTMLElement = document.documentElement): void {
  writeTokens(THEMES[theme], root)
  root.dataset.theme = theme
  root.dataset.density = density
  root.style.colorScheme = theme === 'light' ? 'light' : 'dark'
}
