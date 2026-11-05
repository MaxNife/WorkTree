import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { apiGet, apiSend, setCsrfToken } from '@/api/client'
import { ROLES, type Role } from '@/router/types'

export interface SessionUser {
  id: string
  username: string
  displayName: string
  roles: Role[]
}

type Status = 'unknown' | 'authenticated' | 'anonymous'

// /api/auth/login and /api/auth/me return untyped JSON; narrow it once here.
function readSession(body: unknown): { user: SessionUser; permissions: string[]; csrf: string | null } {
  const data = (body ?? {}) as Record<string, unknown>
  const raw = (data.user ?? {}) as Record<string, unknown>
  const roleList = Array.isArray(raw.roles) ? raw.roles : Array.isArray(data.roles) ? data.roles : []
  const username = String(raw.username ?? '')
  return {
    user: {
      id: String(raw.id ?? ''),
      username,
      displayName: typeof raw.display_name === 'string' && raw.display_name ? raw.display_name : username,
      roles: roleList.filter((role): role is Role => ROLES.includes(role as Role)),
    },
    permissions: Array.isArray(data.permissions) ? data.permissions.map(String) : [],
    csrf: typeof data.csrf_token === 'string' ? data.csrf_token : null,
  }
}

export const useSession = defineStore('session', () => {
  const user = ref<SessionUser | null>(null)
  const permissions = ref<string[]>([])
  const status = ref<Status>('unknown')
  let loading: Promise<void> | null = null

  const roles = computed<Role[]>(() => user.value?.roles ?? [])
  const isAuthenticated = computed(() => status.value === 'authenticated')
  const isAdmin = computed(() => roles.value.includes('admin'))

  function accept(body: unknown): void {
    const session = readSession(body)
    user.value = session.user
    permissions.value = session.permissions
    status.value = 'authenticated'
    setCsrfToken(session.csrf)
  }

  function clear(): void {
    user.value = null
    permissions.value = []
    status.value = 'anonymous'
    loading = null
    setCsrfToken(null)
  }

  /**
   * Load the current session once; concurrent callers share the request. Any failure (401, or the
   * server being unreachable) counts as signed out; the login page reports real errors on submit.
   */
  function ensureLoaded(): Promise<void> {
    if (status.value !== 'unknown') return Promise.resolve()
    loading ??= apiGet('/api/auth/me').then(accept, clear)
    return loading
  }

  async function login(username: string, password: string): Promise<void> {
    accept(await apiSend<unknown>('POST', '/api/auth/login', { username, password }))
  }

  /** Ends the session on the server; local state is cleared even if that call fails. */
  async function logout(): Promise<void> {
    try {
      await apiSend<unknown>('POST', '/api/auth/logout')
    } finally {
      clear()
    }
  }

  /** The server said the session is gone (for example a 401 from another call). */
  function expire(): void {
    clear()
  }

  function hasRole(...wanted: Role[]): boolean {
    return wanted.some((role) => roles.value.includes(role))
  }

  return { user, permissions, status, roles, isAuthenticated, isAdmin, ensureLoaded, login, logout, expire, hasRole }
})
