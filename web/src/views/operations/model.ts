// The Operations API's JSON, narrowed once here: most of these routes are untyped in the OpenAPI schema.
// Only the fields the screens show are read. A run's own `inputs`, `outputs` and `workspace` are left
// out on purpose: the API masks step data but returns those three as stored.

export const ACTIVE_RUN_STATUSES: readonly string[] = ['pending', 'running', 'suspended']
export const ENVIRONMENTS: readonly string[] = ['dev', 'test', 'prod']
export const TRIGGERS: readonly string[] = ['manual', 'cron', 'webhook', 'file', 'dependency', 'subworkflow']

export interface RunSummary {
  id: string
  workflowId: string
  workflowName: string
  version: number | null
  environment: string
  status: string
  trigger: string
  requestedBy: string
  correlationId: string
  parentRunId: string | null
  error: string
  queuedBehind: string | null
  createdAt: string | null
  startedAt: string | null
  finishedAt: string | null
}

export interface StepAttempt {
  attempt: number
  outcome: string
  message: string
  durationMs: number | null
}

export interface RunStep {
  id: string
  stepId: string
  activity: string
  iteration: number
  foreachCount: number
  state: string
  outcome: string
  attempt: number
  message: string
  inputs: unknown
  outputs: unknown
  childRunId: string | null
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
  attempts: StepAttempt[]
}

export interface RunIncident {
  id: string
  stepId: string
  kind: string
  message: string
  resolved: boolean
  createdAt: string | null
}

export interface RunArtifact {
  id: string
  stepId: string
  name: string
  bytes: number | null
  createdAt: string | null
}

export interface RunDetail extends RunSummary {
  steps: RunStep[]
  incidents: RunIncident[]
  artifacts: RunArtifact[]
}

export interface DashboardRun {
  id: string
  workflowName: string
  status: string
  environment: string
  trigger: string
  createdAt: string | null
}

export interface Dashboard {
  running: number
  waiting: number
  failed: number
  openTasks: number
  overdueTasks: number
  recentRuns: DashboardRun[]
}

export interface RunPage {
  items: RunSummary[]
  total: number
}

export interface Schedule {
  id: string
  workflowId: string
  name: string
  kind: string
  cron: string
  timezone: string
  enabled: boolean
  environment: string
  nextRunAt: string | null
  lastRunAt: string | null
}

export interface WorkflowOption {
  id: string
  name: string
}

type Raw = Record<string, unknown>

const asRaw = (value: unknown): Raw => (value !== null && typeof value === 'object' ? (value as Raw) : {})
const asList = (value: unknown): Raw[] => (Array.isArray(value) ? value.map(asRaw) : [])
const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const textOrNull = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const count = (value: unknown): number => numberOrNull(value) ?? 0

export function readRun(value: unknown): RunSummary {
  const raw = asRaw(value)
  const detail = asRaw(raw.trigger_detail)
  return {
    id: text(raw.id),
    workflowId: text(raw.workflow_id),
    workflowName: text(raw.workflow_name),
    version: numberOrNull(raw.version),
    environment: text(raw.environment),
    status: text(raw.status),
    trigger: text(raw.trigger),
    requestedBy: text(raw.requested_by),
    correlationId: text(raw.correlation_id),
    parentRunId: textOrNull(raw.parent_run_id),
    error: text(raw.error),
    queuedBehind: detail.queued === true ? textOrNull(detail.duplicate_of) : null,
    createdAt: textOrNull(raw.created_at),
    startedAt: textOrNull(raw.started_at),
    finishedAt: textOrNull(raw.finished_at),
  }
}

function readStep(raw: Raw): RunStep {
  return {
    id: text(raw.id),
    stepId: text(raw.step_id),
    activity: text(raw.activity),
    iteration: count(raw.iteration),
    foreachCount: count(raw.foreach_count),
    state: text(raw.state),
    outcome: text(raw.outcome),
    attempt: count(raw.attempt),
    message: text(raw.message),
    inputs: raw.inputs,
    outputs: raw.outputs,
    childRunId: textOrNull(raw.child_run_id),
    startedAt: textOrNull(raw.started_at),
    finishedAt: textOrNull(raw.finished_at),
    durationMs: numberOrNull(raw.duration_ms),
    attempts: asList(raw.attempts).map((item) => ({
      attempt: count(item.attempt),
      outcome: text(item.outcome),
      message: text(item.message),
      durationMs: numberOrNull(item.duration_ms),
    })),
  }
}

export function readRunDetail(value: unknown): RunDetail {
  const raw = asRaw(asRaw(value).run)
  return {
    ...readRun(raw),
    steps: asList(raw.steps).map(readStep),
    incidents: asList(raw.incidents).map((item) => ({
      id: text(item.id),
      stepId: text(item.step_id),
      kind: text(item.kind),
      message: text(item.message),
      resolved: item.resolved === true,
      createdAt: textOrNull(item.created_at),
    })),
    artifacts: asList(raw.artifacts).map((item) => ({
      id: text(item.id),
      stepId: text(item.step_id),
      name: text(item.name),
      bytes: numberOrNull(item.bytes),
      createdAt: textOrNull(item.created_at),
    })),
  }
}

export function readRunPage(value: unknown): RunPage {
  const raw = asRaw(value)
  return { items: asList(raw.items).map(readRun), total: count(raw.total) }
}

export function readDashboard(value: unknown): Dashboard {
  const raw = asRaw(value)
  const counts = asRaw(raw.counts)
  return {
    running: count(counts.running),
    waiting: count(counts.suspended),
    failed: count(counts.failed),
    openTasks: count(counts.open_tasks),
    overdueTasks: count(counts.overdue_tasks),
    recentRuns: asList(raw.recent_runs).map((item) => ({
      id: text(item.id),
      workflowName: text(item.workflow_name),
      status: text(item.status),
      environment: text(item.environment),
      trigger: text(item.trigger),
      createdAt: textOrNull(item.created_at),
    })),
  }
}

/** A webhook token never leaves this function: only admins receive it and no screen shows it. */
export function readSchedule(value: unknown): Schedule {
  const raw = asRaw(value)
  return {
    id: text(raw.id),
    workflowId: text(raw.workflow_id),
    name: text(raw.name),
    kind: text(raw.kind),
    cron: text(raw.cron),
    timezone: text(raw.timezone),
    enabled: raw.enabled === true,
    environment: text(raw.environment),
    nextRunAt: textOrNull(raw.next_run_at),
    lastRunAt: textOrNull(raw.last_run_at),
  }
}

export function readWorkflows(value: unknown): WorkflowOption[] {
  return asList(value).map((item) => ({ id: text(item.id), name: text(item.name) }))
}

export const isActive = (status: string): boolean => ACTIVE_RUN_STATUSES.includes(status)

/** From start to finish, or to now while it runs. Null until it has started. */
export function elapsedMs(startedAt: string | null, finishedAt: string | null): number | null {
  if (!startedAt) return null
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now()
  return Number.isNaN(start) || Number.isNaN(end) ? null : Math.max(end - start, 0)
}

/** "manual" to "Manual", for the plain lower-case words the API uses. */
export const titleCase = (word: string): string => (word ? word[0]!.toUpperCase() + word.slice(1) : '')

const sizeFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return '-'
  if (bytes < 1024) return `${sizeFormat.format(bytes)} B`
  if (bytes < 1024 * 1024) return `${sizeFormat.format(bytes / 1024)} KB`
  return `${sizeFormat.format(bytes / (1024 * 1024))} MB`
}

/** What is known about a step, as text: every attempt, then its masked inputs and outputs. */
export function stepLog(step: RunStep): string {
  const lines = step.attempts.map((item) => {
    const head = `Attempt ${item.attempt}: ${item.outcome || 'no outcome'}`
    return item.message ? `${head}\n${item.message}` : head
  })
  for (const [label, value] of [
    ['Inputs', step.inputs],
    ['Outputs', step.outputs],
  ] as const) {
    if (value !== null && value !== undefined) lines.push(`${label}\n${JSON.stringify(value, null, 2)}`)
  }
  return lines.join('\n\n')
}
