// Types shared by the area route modules (router/areas/*.ts), the sidebar and the command palette.
import type { QueryClient } from '@tanstack/vue-query'
import type { RouteLocationNormalizedLoaded, Router, RouteRecordRaw } from 'vue-router'
import type { IconName } from '@/icons/paths'
import type { ToastApi } from '@/stores/toast'

/** Platform roles (app/domain/enums.py). */
export type Role = 'viewer' | 'operator' | 'author' | 'approver' | 'admin'
export const ROLES: readonly Role[] = ['viewer', 'operator', 'author', 'approver', 'admin']

export type AreaId = 'operations' | 'inbox' | 'studio' | 'data' | 'admin'

/** A breadcrumb label: fixed text, or computed from the current route (for example a run id). */
export type BreadcrumbLabel = string | ((route: RouteLocationNormalizedLoaded) => string)

declare module 'vue-router' {
  interface RouteMeta {
    /** Document title; falls back to the breadcrumb label. */
    title?: string
    /** Shown in the breadcrumb trail for this record (parents first). Omit to skip the record. */
    breadcrumb?: BreadcrumbLabel
    /** The user needs at least one of these roles. The API still enforces access. */
    roles?: Role[]
    /** Reachable without signing in (only the login page). */
    public?: boolean
  }
}

/**
 * One sidebar entry. Entries with `to` are links; entries without it only group their children.
 * `loadChildren` fetches children when the entry is shown (cached with vue-query under
 * `['nav', id]`; invalidate `['nav']` to refresh).
 */
export interface NavItem {
  id: string
  label: string
  icon?: IconName
  to?: string
  roles?: Role[]
  children?: NavItem[]
  loadChildren?: () => Promise<NavItem[]>
}

/** What a palette command can use when it runs. */
export interface CommandContext {
  router: Router
  queryClient: QueryClient
  toast: ToastApi
}

export interface PaletteCommand {
  id: string
  label: string
  /** Shown beside the label and searchable, for example "Studio" or "Theme". */
  group: string
  icon?: IconName
  /** Extra words that match the command. */
  keywords?: string[]
  roles?: Role[]
  run: (context: CommandContext) => void | Promise<void>
}

/** What each module in router/areas/ exports. */
export interface AreaModule {
  routes: RouteRecordRaw[]
  navItems: NavItem[]
  commands: PaletteCommand[]
}

/** True when no roles are required or the user has one of them. */
export function allowed(required: readonly Role[] | undefined, roles: readonly Role[]): boolean {
  return !required || required.length === 0 || required.some((role) => roles.includes(role))
}

/** A post-login target from the query string, only if it is a path on this site. */
export function safeRedirect(value: unknown): string | null {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\')
    ? value
    : null
}
