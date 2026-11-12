// The old `uaf` names, accepted for one release after the rename to WorkTree (docs/03 Part 3).
// Everything in the web client that still knows them lives here, so removing them is one file.

/** The readable CSRF cookie: the new name first, then the one set before the rename. */
const CSRF_COOKIES = ['worktree_csrf', 'uaf_csrf'] as const

export function csrfCookie(): string | null {
  if (typeof document === 'undefined') return null
  const parts = document.cookie.split('; ')
  for (const name of CSRF_COOKIES) {
    const match = parts.find((part) => part.startsWith(`${name}=`))
    if (match) return decodeURIComponent(match.slice(name.length + 1))
  }
  return null
}

/**
 * Read `key` from localStorage, moving a value stored under `legacyKey` before the rename to the
 * new key once. Storage can be missing or throw (private windows, blocked site data).
 */
export function readStored(key: string, legacyKey: string): string | null {
  try {
    const current = window.localStorage.getItem(key)
    if (current !== null) return current
    const legacy = window.localStorage.getItem(legacyKey)
    if (legacy !== null) {
      window.localStorage.setItem(key, legacy)
      window.localStorage.removeItem(legacyKey)
    }
    return legacy
  } catch {
    return null
  }
}
