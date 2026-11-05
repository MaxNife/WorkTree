// Query keys and calls for the Operations screens. Keys are stable: a time range stays a token here and
// becomes a timestamp only inside the request, so it never changes the key.
import { ApiError, apiGet, apiSend, buildUrl } from '@/api/client'
import { sinceFor, type RunFilters } from './filters'
import {
  readDashboard,
  readRun,
  readRunDetail,
  readRunPage,
  readSchedule,
  readWorkflows,
  type Dashboard,
  type RunDetail,
  type RunPage,
  type RunSummary,
  type Schedule,
  type WorkflowOption,
} from './model'

export const operationsKeys = {
  all: ['operations'] as const,
  dashboard: ['operations', 'dashboard'] as const,
  attention: ['operations', 'attention'] as const,
  runs: ['operations', 'runs'] as const,
  runList: (filters: RunFilters) => ['operations', 'runs', filters] as const,
  run: (runId: string) => ['operations', 'run', runId] as const,
  schedules: ['operations', 'schedules'] as const,
  workflows: ['operations', 'workflows'] as const,
  runnable: (workflowId: string, environment: string) => ['operations', 'runnable', workflowId, environment] as const,
}

export const fetchDashboard = async (signal?: AbortSignal): Promise<Dashboard> =>
  readDashboard(await apiGet('/api/dashboard', { signal }))

export async function fetchRuns(filters: RunFilters, limit: number, signal?: AbortSignal): Promise<RunPage> {
  const body = await apiGet('/api/runs', {
    signal,
    query: {
      q: filters.q || undefined,
      status: filters.status.length ? filters.status : undefined,
      environment: filters.environment || undefined,
      trigger: filters.trigger || undefined,
      since: sinceFor(filters.range, Date.now()),
      sort: filters.sort,
      limit,
      offset: filters.offset,
    },
  })
  return readRunPage(body)
}

export async function fetchFailedRuns(limit: number, signal?: AbortSignal): Promise<RunSummary[]> {
  const body = await apiGet('/api/runs', { signal, query: { status: ['failed'], sort: '-created_at', limit } })
  return readRunPage(body).items
}

export const fetchRun = async (runId: string, signal?: AbortSignal): Promise<RunDetail> =>
  readRunDetail(await apiGet('/api/runs/{run_id}', { path: { run_id: runId }, signal }))

export const fetchSchedules = async (signal?: AbortSignal): Promise<Schedule[]> => {
  const body = await apiGet('/api/schedules', { signal })
  return (Array.isArray(body) ? body : []).map(readSchedule)
}

export const fetchWorkflows = async (signal?: AbortSignal): Promise<WorkflowOption[]> =>
  readWorkflows(await apiGet('/api/workflows', { signal }))

/** The version this workflow would run in that environment. An error says why it cannot run. */
export async function fetchRunnableVersion(workflowId: string, environment: string, signal?: AbortSignal): Promise<number | null> {
  const body = await apiGet('/api/workflows/{workflow_id}/runnable', {
    signal,
    path: { workflow_id: workflowId },
    query: { environment },
  } as Parameters<typeof apiGet>[1])
  const version = (body as { version?: unknown }).version
  return typeof version === 'number' ? version : null
}

const runAction = (runId: string, action: 'retry' | 'cancel'): Promise<unknown> =>
  apiSend('POST', buildUrl(`/api/runs/{run_id}/${action}`, { path: { run_id: runId } }))

export const retryRun = (runId: string): Promise<unknown> => runAction(runId, 'retry')
export const cancelRun = (runId: string): Promise<unknown> => runAction(runId, 'cancel')

export const setScheduleEnabled = (scheduleId: string, enabled: boolean): Promise<unknown> =>
  apiSend('POST', buildUrl('/api/schedules/{schedule_id}/enabled', { path: { schedule_id: scheduleId } }), { enabled })

export type StartRunResult =
  | { kind: 'started'; run: RunSummary }
  /** The duplicate guard refused: this run with the same key is still active. */
  | { kind: 'duplicate'; activeRunId: string }

const CSRF_COOKIE = 'uaf_csrf'

function csrfToken(): string | null {
  const match = document.cookie.split('; ').find((part) => part.startsWith(`${CSRF_COOKIE}=`))
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : null
}

interface ErrorBody {
  error?: { code?: string; message?: string; details?: { duplicate_of?: unknown } }
}

/**
 * POST /api/workflows/{id}/run. This one call needs what `apiSend` cannot do: send `Idempotency-Key`
 * and read `error.details`, where the duplicate guard names the active run.
 */
export async function startRun(
  workflowId: string,
  request: { environment: string; inputs: Record<string, unknown> },
  idempotencyKey: string,
): Promise<StartRunResult> {
  const token = csrfToken()
  const response = await fetch(buildUrl('/api/workflows/{workflow_id}/run', { path: { workflow_id: workflowId } }), {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
      ...(token ? { 'X-CSRF-Token': token } : {}),
    },
    body: JSON.stringify(request),
  })
  const body = (await response.json().catch(() => ({}))) as ErrorBody & { run?: unknown }
  if (response.ok) return { kind: 'started', run: readRun(body.run) }
  const { code = 'http_error', message = response.statusText || `HTTP ${response.status}`, details } = body.error ?? {}
  if (code === 'duplicate_run' && typeof details?.duplicate_of === 'string') {
    return { kind: 'duplicate', activeRunId: details.duplicate_of }
  }
  throw new ApiError(response.status, code, message)
}

/** A key per dialog open. getRandomValues, because randomUUID needs HTTPS and this may be plain HTTP. */
export function newIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

/** Server messages start in lower case; screens show sentence case. */
export function sentence(message: string): string {
  return message.charAt(0).toUpperCase() + message.slice(1)
}

/** Polite words for a failed action: a 403 is about the user's role, not a fault. */
export function actionError(error: unknown, action: string): string {
  if (error instanceof ApiError && error.status === 403) return `You do not have permission to ${action}.`
  return error instanceof Error && error.message ? sentence(error.message) : `Could not ${action}.`
}
