// Which sidebar entry is current (docs/04 5, "exact-match highlighting"). Only one entry is ever
// current: the one whose link is the longest match for the path, and the deepest when a parent and
// its child share a link (Operations and Dashboard are both /operations). So /operations/runs/abc
// lights Runs and not also Dashboard.
import { inject, type InjectionKey } from 'vue'

export interface NavEntry {
  id: string
  to: string
  depth: number
}

/** True when `path` is `to` or lies under it. */
export function pathMatches(to: string, path: string): boolean {
  if (to === '/') return true
  return path === to || path.startsWith(`${to}/`)
}

/** The id of the current entry for `path`, or undefined when nothing matches. */
export function currentNavId(entries: Iterable<NavEntry>, path: string): string | undefined {
  let best: NavEntry | undefined
  for (const entry of entries) {
    if (!pathMatches(entry.to, path)) continue
    if (!best || entry.to.length > best.to.length || (entry.to.length === best.to.length && entry.depth > best.depth)) {
      best = entry
    }
  }
  return best?.id
}

/** The sidebar's registry: every shown entry with a link registers itself while it is mounted. */
export interface NavRegistry {
  register: (entry: NavEntry) => void
  unregister: (id: string) => void
  isCurrent: (id: string) => boolean
}

export const NAV_REGISTRY: InjectionKey<NavRegistry> = Symbol('nav-registry')

export function useNavRegistry(): NavRegistry | undefined {
  return inject(NAV_REGISTRY, undefined)
}
