// Run history filters as they live in the URL. Reading tolerates anything a pasted link can hold: what
// the API would refuse is dropped here, so a bad link shows the unfiltered list and not an error.
import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import { ENVIRONMENTS, TRIGGERS } from './model'

export const RUN_STATUSES: readonly string[] = ['pending', 'running', 'suspended', 'done', 'failed', 'cancelled']
export const DEFAULT_SORT = '-created_at'
export const PAGE_SIZE = 25

const SORT_COLUMNS: readonly string[] = ['created_at', 'status', 'workflow_name', 'environment']
const SEARCH_LIMIT = 200

export const TIME_RANGES = [
  { value: '', label: 'All time', ms: null },
  { value: '24h', label: 'Last 24 hours', ms: 24 * 3_600_000 },
  { value: '7d', label: 'Last 7 days', ms: 7 * 24 * 3_600_000 },
  { value: '30d', label: 'Last 30 days', ms: 30 * 24 * 3_600_000 },
] as const

export interface RunFilters {
  q: string
  status: string[]
  environment: string
  trigger: string
  range: string
  sort: string
  offset: number
}

function first(value: LocationQuery[string] | undefined): string {
  const item = Array.isArray(value) ? value[0] : value
  return item ?? ''
}

const oneOf = (value: string, allowed: readonly string[]): string => (allowed.includes(value) ? value : '')

export function readRunFilters(query: LocationQuery): RunFilters {
  const statuses = [query.status ?? []].flat().filter((item): item is string => item !== null)
  const sort = first(query.sort)
  const offset = Number(first(query.offset))
  return {
    q: first(query.q).slice(0, SEARCH_LIMIT),
    status: statuses.filter((item) => RUN_STATUSES.includes(item)).sort(),
    environment: oneOf(first(query.environment), ENVIRONMENTS),
    trigger: oneOf(first(query.trigger), TRIGGERS),
    range: oneOf(first(query.range), TIME_RANGES.map((range) => range.value)),
    sort: SORT_COLUMNS.includes(sort.replace(/^-/, '')) ? sort : DEFAULT_SORT,
    offset: Number.isSafeInteger(offset) && offset > 0 ? offset : 0,
  }
}

/** Only what differs from the default, so a plain list has a plain URL. */
export function writeRunFilters(filters: RunFilters): LocationQueryRaw {
  return {
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.status.length ? { status: filters.status } : {}),
    ...(filters.environment ? { environment: filters.environment } : {}),
    ...(filters.trigger ? { trigger: filters.trigger } : {}),
    ...(filters.range ? { range: filters.range } : {}),
    ...(filters.sort !== DEFAULT_SORT ? { sort: filters.sort } : {}),
    ...(filters.offset ? { offset: String(filters.offset) } : {}),
  }
}

export function hasActiveFilters(filters: RunFilters): boolean {
  return Boolean(filters.q || filters.status.length || filters.environment || filters.trigger || filters.range)
}

/** The start of a time range as the API wants it, or nothing for all time. */
export function sinceFor(range: string, now: number): string | undefined {
  const ms = TIME_RANGES.find((item) => item.value === range)?.ms
  return ms ? new Date(now - ms).toISOString() : undefined
}
