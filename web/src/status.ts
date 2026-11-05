// Status vocabulary shared by badges, the run timeline and node cards. Mirrors app/domain/enums.py.

export type StatusKind = 'ok' | 'danger' | 'warn' | 'attention' | 'neutral' | 'running'

export interface StatusStyle {
  kind: StatusKind
  label: string
}

const STATUSES = new Map<string, StatusStyle>([
  // RunStatus
  ['pending', { kind: 'neutral', label: 'Pending' }],
  ['running', { kind: 'running', label: 'Running' }],
  ['suspended', { kind: 'warn', label: 'Waiting' }],
  ['done', { kind: 'ok', label: 'Done' }],
  ['failed', { kind: 'danger', label: 'Failed' }],
  ['cancelled', { kind: 'neutral', label: 'Cancelled' }],
  // StepState (adds)
  ['dispatched', { kind: 'running', label: 'Running' }],
  ['waiting', { kind: 'warn', label: 'Waiting' }],
  ['skipped', { kind: 'neutral', label: 'Skipped' }],
  // TaskStatus (adds)
  ['open', { kind: 'attention', label: 'Open' }],
  ['claimed', { kind: 'running', label: 'Claimed' }],
  ['completed', { kind: 'ok', label: 'Completed' }],
])

/** Every backend status with a style of its own. */
export const STATUS_NAMES: readonly string[] = [...STATUSES.keys()]

/** Style for a backend status string; unknown values render as a neutral badge with their name. */
export function statusStyle(status: string): StatusStyle {
  return STATUSES.get(status) ?? { kind: 'neutral', label: status }
}

/** Format milliseconds as a short duration: 850 ms, 4.2 s, 3 m 05 s, 1 h 02 m. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '-'
  const total = Math.round(ms)
  if (total < 1000) return `${total} ms`
  // Each unit rounds down, so a time never shows a full next unit (60 s, 60 m) before it gets there.
  if (total < 10_000) return `${(Math.floor(total / 100) / 10).toFixed(1)} s`
  const seconds = Math.floor(total / 1000)
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} m ${String(seconds % 60).padStart(2, '0')} s`
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} m`
}
