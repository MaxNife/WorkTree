import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, type Router } from 'vue-router'
import App from '@/App.vue'
import { navigationCommands } from '@/components/shell/commands'
import UDialog from '@/components/UDialog.vue'
import USelect from '@/components/USelect.vue'
import USwitch from '@/components/USwitch.vue'
import UTextArea from '@/components/UTextArea.vue'
import { createAppRouter } from '@/router'
import { AREAS } from '@/router/areas'
import type { Role } from '@/router/types'
import { contrastRatio, THEMES } from '@/theme/tokens'
import { readRunFilters, sinceFor, writeRunFilters } from '@/views/operations/filters'
import { stepLog, readRunDetail } from '@/views/operations/model'

// What Fluent gives these tests: a <dialog> in a shadow root and the <textarea> it exposes.
const backdropClick = vi.fn()
class StubDialog extends HTMLElement {
  inner = document.createElement('dialog')
  constructor() {
    super()
    this.attachShadow({ mode: 'open' }).append(this.inner)
    this.inner.addEventListener('click', backdropClick)
  }
}
class StubTextArea extends HTMLElement {
  controlEl = document.createElement('textarea')
}
customElements.define('fluent-dialog', StubDialog)
customElements.define('fluent-textarea', StubTextArea)

class FakeSocket {
  static instances: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((message: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  constructor() {
    FakeSocket.instances.push(this)
  }
  close(): void {}
  open(): void {
    this.onopen?.()
  }
  send(event: unknown): void {
    this.onmessage?.({ data: JSON.stringify(event) })
  }
  drop(code = 1006): void {
    this.onclose?.({ code })
  }
}

const PERMISSIONS: Record<Role, string[]> = {
  viewer: ['view'],
  operator: ['view', 'run.trigger', 'run.retry'],
  author: ['view', 'run.trigger'],
  approver: ['view'],
  admin: ['view', 'run.trigger', 'run.retry', 'admin.schedules'],
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function runRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 'r1',
    workflow_id: 'w1',
    workflow_name: 'Reconcile',
    version: 3,
    environment: 'dev',
    status: 'done',
    trigger: 'manual',
    trigger_detail: {},
    correlation_id: 'c1',
    error: '',
    requested_by: 'ada',
    parent_run_id: null,
    created_at: '2026-11-05T10:00:00+00:00',
    started_at: '2026-11-05T10:00:01+00:00',
    finished_at: '2026-11-05T10:00:05+00:00',
    steps: [],
    incidents: [],
    artifacts: [],
    ...overrides,
  }
}

const stepRow = (overrides: Record<string, unknown> = {}) => ({
  id: 's1',
  step_id: 'fetch',
  activity: 'sleep',
  iteration: 0,
  foreach_count: 0,
  state: 'done',
  outcome: 'done',
  attempt: 1,
  inputs: { url: '***' },
  outputs: { rows: 2 },
  message: '',
  child_run_id: null,
  started_at: '2026-11-05T10:00:01+00:00',
  finished_at: '2026-11-05T10:00:03+00:00',
  duration_ms: 2000,
  attempts: [{ attempt: 1, outcome: 'done', message: '', duration_ms: 2000 }],
  ...overrides,
})

interface Server {
  roles: Role[]
  run?: Record<string, unknown>
  runs?: Record<string, unknown>[]
  total?: number
  schedules?: Record<string, unknown>[]
  dashboard?: Record<string, unknown>
  start?: () => Response
  runnable?: () => Response
  toggle?: () => Response
}

const DASHBOARD = {
  counts: { running: 2, suspended: 1, failed: 4, open_tasks: 5, overdue_tasks: 6 },
  recent_runs: [],
}

function stubServer(server: Server) {
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, 'http://test')
    const path = url.pathname
    const post = init?.method === 'POST'
    if (path === '/api/auth/me') {
      return json(200, {
        user: { id: 'u1', username: 'ada', display_name: 'Ada', roles: server.roles },
        roles: server.roles,
        permissions: server.roles.flatMap((role) => PERMISSIONS[role]),
        csrf_token: 'tok-1',
      })
    }
    if (path === '/api/dashboard') return json(200, server.dashboard ?? DASHBOARD)
    if (path === '/api/runs') return json(200, { items: server.runs ?? [], total: server.total ?? (server.runs ?? []).length })
    if (path === '/api/schedules') return json(200, server.schedules ?? [])
    if (/^\/api\/schedules\/.+\/enabled$/.test(path)) return server.toggle?.() ?? json(200, {})
    if (path === '/api/workflows') return json(200, [{ id: 'w1', name: 'Reconcile' }])
    if (path.endsWith('/runnable')) return server.runnable?.() ?? json(200, { version: 3 })
    if (path.endsWith('/run') && post) return server.start?.() ?? json(200, { run: runRow({ id: 'new-run' }) })
    if (/^\/api\/runs\/.+\/(retry|cancel)$/.test(path)) return json(200, { run: runRow() })
    if (path.startsWith('/api/runs/')) return json(200, { run: server.run ?? runRow({ id: path.split('/').pop() }) })
    return json(404, { error: { code: 'not_found', message: path } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

let wrapper: VueWrapper | null = null
let client: QueryClient

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await flushPromises()
    await vi.dynamicImportSettled()
  }
}

/** The same, with the clock faked: flushPromises would wait for a timer nothing advances. */
async function settleFaked(): Promise<void> {
  for (let i = 0; i < 6; i++) {
    await vi.advanceTimersByTimeAsync(10)
    await vi.dynamicImportSettled()
  }
}

async function mountApp(path: string, server: Server, faked = false) {
  const fetchMock = stubServer(server)
  const pinia = createPinia()
  setActivePinia(pinia)
  const router: Router = createAppRouter(createMemoryHistory(), pinia)
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  void router.push(path)
  if (faked) await settleFaked()
  await router.isReady()
  wrapper = mount(App, { attachTo: document.body, global: { plugins: [pinia, router, [VueQueryPlugin, { queryClient: client }]] } })
  await (faked ? settleFaked() : settle())
  return { router, fetchMock }
}

type FetchMock = ReturnType<typeof stubServer>

const calls = (fetchMock: FetchMock, match: (url: URL, init?: RequestInit) => boolean) =>
  fetchMock.mock.calls.filter(([input, init]) => match(new URL(input, 'http://test'), init))

const runDetailCalls = (fetchMock: FetchMock, id = 'r1') => calls(fetchMock, (url) => url.pathname === `/api/runs/${id}`).length
const lastRunsQuery = (fetchMock: FetchMock) =>
  new URL(calls(fetchMock, (url) => url.pathname === '/api/runs').at(-1)![0], 'http://test').searchParams

function select(label: string) {
  return wrapper!.findAllComponents(USelect).find((item) => item.props('label') === label)!
}

async function button(text: string): Promise<void> {
  const target = wrapper!.findAll('fluent-button').find((item) => item.text() === text)
  if (!target) throw new Error(`no button "${text}"`)
  await target.trigger('click')
}

const hasButton = (text: string): boolean => wrapper!.findAll('fluent-button').some((item) => item.text() === text)

const socket = (): FakeSocket => FakeSocket.instances.at(-1)!

beforeEach(() => {
  window.localStorage.clear()
  document.body.innerHTML = ''
  document.cookie = 'uaf_csrf=tok-1'
  FakeSocket.instances = []
  backdropClick.mockClear()
  vi.stubGlobal('WebSocket', FakeSocket)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  client?.clear()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('run filters in the URL', () => {
  it('reads what a link holds and drops what the API would refuse', () => {
    expect(
      readRunFilters({ status: ['pending', 'nonsense'], environment: 'mars', trigger: 'cron', range: '1y', sort: '-password', offset: '-5', q: 'abc' }),
    ).toEqual({ q: 'abc', status: ['pending'], environment: '', trigger: 'cron', range: '', sort: '-created_at', offset: 0 })
  })

  it('leaves defaults out of the URL and round-trips the rest', () => {
    const filters = readRunFilters({ status: ['pending', 'running'], range: '7d', sort: 'status', offset: '25' })
    expect(writeRunFilters(readRunFilters({}))).toEqual({})
    expect(readRunFilters(writeRunFilters(filters) as never)).toEqual(filters)
  })

  it('turns a range into a start time only for the request', () => {
    const now = Date.UTC(2026, 10, 5)
    expect(sinceFor('', now)).toBeUndefined()
    expect(sinceFor('24h', now)).toBe('2026-11-04T00:00:00.000Z')
  })
})

describe('run history', () => {
  const runs = [runRow()]

  it('sends the filters, sort and page from the URL to the API', async () => {
    const { fetchMock } = await mountApp('/operations/runs?status=failed&status=cancelled&environment=prod&range=7d&sort=-status&offset=25&q=abc', {
      roles: ['viewer'],
      runs,
      total: 60,
    })
    const query = lastRunsQuery(fetchMock)
    expect(query.getAll('status')).toEqual(['cancelled', 'failed'])
    expect(query.get('environment')).toBe('prod')
    expect(query.get('sort')).toBe('-status')
    expect(query.get('offset')).toBe('25')
    expect(query.get('q')).toBe('abc')
    expect(query.get('since')).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })

  it('writes a filter to the URL and goes back to the first page', async () => {
    const { router, fetchMock } = await mountApp('/operations/runs?offset=25', { roles: ['viewer'], runs, total: 60 })
    select('Environment').vm.$emit('update:modelValue', 'test')
    await settle()
    expect(router.currentRoute.value.query).toEqual({ environment: 'test' })
    expect(lastRunsQuery(fetchMock).get('offset')).toBe('0')
  })

  it('keeps a combined status as two values', async () => {
    const { router, fetchMock } = await mountApp('/operations/runs', { roles: ['viewer'], runs })
    select('Status').vm.$emit('update:modelValue', 'pending,running')
    await settle()
    expect(router.currentRoute.value.query.status).toEqual(['pending', 'running'])
    expect(lastRunsQuery(fetchMock).getAll('status')).toEqual(['pending', 'running'])
    expect(select('Status').props('modelValue')).toBe('pending,running')
  })

  it('sorts on the server through the URL', async () => {
    const { router, fetchMock } = await mountApp('/operations/runs', { roles: ['viewer'], runs })
    await wrapper!.findAll('th button').find((item) => item.text() === 'Workflow')!.trigger('click')
    await settle()
    expect(router.currentRoute.value.query.sort).toBe('-workflow_name')
    expect(lastRunsQuery(fetchMock).get('sort')).toBe('-workflow_name')
  })

  it('offers sorting only on what the API can sort by', async () => {
    await mountApp('/operations/runs', { roles: ['viewer'], runs })
    expect(wrapper!.findAll('th button').map((item) => item.text())).toEqual(['Status', 'Workflow', 'Environment', 'Started'])
  })

  it('pages through the URL', async () => {
    const { router, fetchMock } = await mountApp('/operations/runs', { roles: ['viewer'], runs, total: 60 })
    const next = wrapper!.findAll('nav[aria-label="Pagination"] fluent-button').at(-1)!
    await next.trigger('click')
    await settle()
    expect(router.currentRoute.value.query.offset).toBe('25')
    expect(lastRunsQuery(fetchMock).get('offset')).toBe('25')
  })

  it('opens a run from its row', async () => {
    const { router } = await mountApp('/operations/runs', { roles: ['viewer'], runs })
    await wrapper!.get('tbody tr').trigger('click')
    await settle()
    expect(router.currentRoute.value.fullPath).toBe('/operations/runs/r1')
  })

  it('says how to get out of an empty filtered list', async () => {
    await mountApp('/operations/runs?status=failed', { roles: ['viewer'], runs: [] })
    expect(wrapper!.text()).toContain('No matching runs')
  })

  it('keeps one cache entry for a time range while it polls', async () => {
    vi.useFakeTimers()
    await mountApp('/operations/runs?range=24h', { roles: ['viewer'], runs: [runRow({ status: 'running' })] }, true)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(client.getQueryCache().findAll({ queryKey: ['operations', 'runs'] })).toHaveLength(1)
  })
})

describe('dashboard', () => {
  it('links each number to the view behind it, with pending inside running', async () => {
    await mountApp('/operations', { roles: ['viewer'] })
    const hrefs = Object.fromEntries(wrapper!.findAll('.numbers__item').map((item) => [item.get('dt').text(), item.get('a').attributes('href')]))
    expect(hrefs).toEqual({
      Running: '/operations/runs?status=pending&status=running',
      Waiting: '/operations/runs?status=suspended',
      Failed: '/operations/runs?status=failed',
      'Open tasks': '/inbox',
      'Overdue tasks': '/inbox',
    })
    expect(wrapper!.get('.numbers').text()).toContain('6')
  })

  it('lists failed runs under needs attention', async () => {
    await mountApp('/operations', { roles: ['viewer'], runs: [runRow({ status: 'failed', error: 'Target refused' })] })
    expect(wrapper!.get('.attention').text()).toContain('Target refused')
    expect(wrapper!.get('.attention a').attributes('href')).toBe('/operations/runs/r1')
  })
})

describe('run detail', () => {
  const failed = runRow({
    status: 'failed',
    error: 'Boom',
    steps: [
      stepRow(),
      stepRow({ id: 's2', step_id: 'post', state: 'failed', outcome: 'failed', message: 'Boom', attempt: 3, attempts: [{ attempt: 1 }, { attempt: 2 }, { attempt: 3, outcome: 'failed', message: 'Boom' }] }),
    ],
    incidents: [{ id: 'i1', step_id: 'post', kind: 'retry_exhausted', message: 'Gave up', resolved: false, created_at: null }],
    artifacts: [{ id: 'a/1', step_id: 'post', name: 'report.xlsx', bytes: 2048, created_at: null }],
  })

  it('opens the failed step, with its retries, incidents and masked log', async () => {
    await mountApp('/operations/runs/r1', { roles: ['viewer'], run: failed })
    const items = wrapper!.findAll('.run-timeline__item')
    expect(items[0]!.find('details').attributes('open')).toBeUndefined()
    expect(items[1]!.find('details').attributes('open')).toBeDefined()
    expect(items[1]!.text()).toContain('Retried 2 times')
    expect(items[1]!.text()).toContain('Gave up')
    expect(items[0]!.text()).toContain('***')
  })

  it('shows the workflow name, status and counts on the tabs', async () => {
    await mountApp('/operations/runs/r1', { roles: ['viewer'], run: failed })
    expect(wrapper!.get('h1').text()).toBe('Reconcile')
    expect(wrapper!.get('.page-header__actions [data-status]').attributes('data-status')).toBe('failed')
    expect(wrapper!.findAll('[role="tab"]').map((tab) => tab.text().replace(/\s+/g, ' '))).toEqual(['Steps 2', 'Artifacts 1', 'Incidents 1'])
  })

  it('links artifacts to their download, keeping the id as one path segment', async () => {
    await mountApp('/operations/runs/r1?tab=artifacts', { roles: ['viewer'], run: failed })
    expect(wrapper!.get('a[download]').attributes('href')).toBe('/api/artifacts/a%2F1/download')
    expect(wrapper!.text()).toContain('2 KB')
  })

  it('retries from the failed step', async () => {
    const { fetchMock } = await mountApp('/operations/runs/r1', { roles: ['operator'], run: failed })
    await button('Retry from failed step')
    await settle()
    expect(calls(fetchMock, (url, init) => url.pathname === '/api/runs/r1/retry' && init?.method === 'POST')).toHaveLength(1)
  })

  it('offers cancel on an active run and only acts after confirming', async () => {
    const run = runRow({ status: 'running', finished_at: null })
    const { fetchMock } = await mountApp('/operations/runs/r1', { roles: ['operator'], run })
    expect(hasButton('Retry from failed step')).toBe(false)
    await button('Cancel')
    await settle()
    expect(calls(fetchMock, (url) => url.pathname === '/api/runs/r1/cancel')).toHaveLength(0)
    await button('Cancel run')
    await settle()
    expect(calls(fetchMock, (url) => url.pathname === '/api/runs/r1/cancel')).toHaveLength(1)
  })

  it('hides retry and cancel from those without run.retry', async () => {
    await mountApp('/operations/runs/r1', { roles: ['author'], run: failed })
    expect(hasButton('Retry from failed step')).toBe(false)
    wrapper!.unmount()
    wrapper = null
    await mountApp('/operations/runs/r1', { roles: ['viewer'], run: runRow({ status: 'running', finished_at: null }) })
    expect(wrapper!.get('.page-header__actions').text()).not.toContain('Cancel')
  })

  it('answers a 403 politely', async () => {
    const { fetchMock } = await mountApp('/operations/runs/r1', { roles: ['operator'], run: failed })
    fetchMock.mockImplementationOnce(async () => json(403, { error: { code: 'forbidden', message: 'role x is not allowed to run.retry' } }))
    await button('Retry from failed step')
    await settle()
    expect(document.body.textContent).toContain('You do not have permission to retry this run.')
  })

  it('shows what a queued run is waiting for', async () => {
    const run = runRow({ status: 'pending', started_at: null, finished_at: null, trigger_detail: { queued: true, duplicate_of: 'ahead' } })
    await mountApp('/operations/runs/r1', { roles: ['viewer'], run })
    expect(wrapper!.text()).toContain('This run starts when the run ahead of it finishes.')
    expect(wrapper!.get('.message-bar a').attributes('href')).toBe('/operations/runs/ahead')
  })

  it('builds the log from masked step data only', () => {
    const run = readRunDetail({ run: { inputs: { password: 'plain' }, workspace: 'C:/secret', steps: [stepRow()] } })
    expect(stepLog(run.steps[0]!)).toContain('***')
    expect(JSON.stringify(run)).not.toContain('plain')
    expect(JSON.stringify(run)).not.toContain('C:/secret')
  })
})

describe('live updates', () => {
  const active = { roles: ['viewer'] as Role[], run: runRow({ status: 'running', finished_at: null }) }
  const finished = { roles: ['viewer'] as Role[], run: runRow() }

  async function mountConnected(path: string, server: Server) {
    vi.useFakeTimers()
    const mounted = await mountApp(path, server, true)
    socket().open()
    await settleFaked()
    return mounted
  }

  it.each(['step.completed', 'run.finished'])('refetches on %s', async (type) => {
    const { fetchMock } = await mountConnected('/operations/runs/r1', finished)
    const before = runDetailCalls(fetchMock)
    socket().send({ type, run_id: 'r1' })
    await vi.advanceTimersByTimeAsync(300)
    expect(runDetailCalls(fetchMock)).toBe(before + 1)
  })

  it('answers a burst of events with one refetch', async () => {
    const { fetchMock } = await mountConnected('/operations/runs/r1', finished)
    const before = runDetailCalls(fetchMock)
    for (let i = 0; i < 5; i++) socket().send({ type: 'step.completed', run_id: 'r1' })
    await vi.advanceTimersByTimeAsync(300)
    expect(runDetailCalls(fetchMock)).toBe(before + 1)
  })

  it('leaves another run alone and ignores ping', async () => {
    const { fetchMock } = await mountConnected('/operations/runs/r1', finished)
    const before = runDetailCalls(fetchMock)
    socket().send({ type: 'ping' })
    socket().send({ type: 'step.completed', run_id: 'other' })
    await vi.advanceTimersByTimeAsync(10_000)
    expect(runDetailCalls(fetchMock)).toBe(before)
  })

  it('refreshes the dashboard and the run list on an event', async () => {
    const { fetchMock } = await mountConnected('/operations', { roles: ['viewer'], dashboard: { ...DASHBOARD, counts: {} } })
    const dashboardCalls = () => calls(fetchMock, (url) => url.pathname === '/api/dashboard').length
    const before = dashboardCalls()
    socket().send({ type: 'run.finished', run_id: 'r1' })
    await vi.advanceTimersByTimeAsync(300)
    expect(dashboardCalls()).toBe(before + 1)
  })

  it('polls every 3 s while the run is active and stops when it finishes', async () => {
    const server: Server = { ...active }
    const { fetchMock } = await mountConnected('/operations/runs/r1', server)
    const before = runDetailCalls(fetchMock)
    await vi.advanceTimersByTimeAsync(6_100)
    expect(runDetailCalls(fetchMock)).toBe(before + 2)
    server.run = runRow()
    await vi.advanceTimersByTimeAsync(3_100)
    const after = runDetailCalls(fetchMock)
    await vi.advanceTimersByTimeAsync(12_000)
    expect(runDetailCalls(fetchMock)).toBe(after)
  })

  it('does not poll a finished run while the socket is up', async () => {
    const { fetchMock } = await mountConnected('/operations/runs/r1', finished)
    const before = runDetailCalls(fetchMock)
    await vi.advanceTimersByTimeAsync(12_000)
    expect(runDetailCalls(fetchMock)).toBe(before)
  })

  it('starts polling a finished run as soon as the socket drops, and stops when it returns', async () => {
    const { fetchMock } = await mountConnected('/operations/runs/r1', finished)
    const before = runDetailCalls(fetchMock)
    socket().drop()
    await vi.advanceTimersByTimeAsync(5_000)
    expect(runDetailCalls(fetchMock)).toBeGreaterThan(before)
    socket().open()
    await settleFaked()
    const after = runDetailCalls(fetchMock)
    await vi.advanceTimersByTimeAsync(12_000)
    expect(runDetailCalls(fetchMock)).toBe(after)
  })

  it('stops polling a run that does not exist', async () => {
    vi.useFakeTimers()
    const { fetchMock } = await mountApp('/operations/runs/r1', { roles: ['viewer'] }, true)
    fetchMock.mockImplementation(async () => json(404, { error: { code: 'not_found', message: 'run r1 not found' } }))
    await vi.advanceTimersByTimeAsync(3_100)
    const after = fetchMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(12_000)
    expect(fetchMock.mock.calls.length).toBe(after)
  })

  it('says plainly when a run does not exist', async () => {
    const { fetchMock } = await mountApp('/operations/runs', { roles: ['viewer'] })
    fetchMock.mockImplementation(async () => json(404, { error: { code: 'not_found', message: 'run r1 not found' } }))
    await wrapper!.vm.$router.push('/operations/runs/r1')
    await settle()
    expect(wrapper!.text()).toContain('This run does not exist.')
  })

  it('says live updates are paused only after 10 s down', async () => {
    await mountConnected('/operations/runs/r1', finished)
    socket().drop()
    await vi.advanceTimersByTimeAsync(9_500)
    expect(wrapper!.text()).not.toContain('Live updates paused')
    await vi.advanceTimersByTimeAsync(1_000)
    expect(wrapper!.text()).toContain('Live updates paused')
    socket().open()
    await settleFaked()
    expect(wrapper!.text()).not.toContain('Live updates paused')
  })
})

describe('run now', () => {
  async function openDialog(server: Partial<Server> = {}, path = '/operations') {
    const mounted = await mountApp(path, { roles: ['operator'], ...server })
    await button('Run now')
    await settle()
    return mounted
  }

  async function choose(): Promise<void> {
    select('Workflow').vm.$emit('update:modelValue', 'w1')
    await settle()
  }

  const startCalls = (fetchMock: FetchMock) => calls(fetchMock, (url, init) => url.pathname === '/api/workflows/w1/run' && init?.method === 'POST')
  const keyOf = (call: [string, RequestInit?]) => (call[1]?.headers as Record<string, string>)['Idempotency-Key']
  const dialogButton = (text: string) => wrapper!.findAll('[slot="action"] fluent-button').find((item) => item.text() === text)!

  it('hides Run now from those who cannot trigger runs', async () => {
    await mountApp('/operations?run=1', { roles: ['viewer'] })
    expect(hasButton('Run now')).toBe(false)
    expect(wrapper!.find('.run-now').exists()).toBe(false)
  })

  it('offers Run now to an author, who can trigger but not retry', async () => {
    await mountApp('/operations', { roles: ['author'] })
    expect(hasButton('Run now')).toBe(true)
  })

  it('goes to the run on success, sending the CSRF token', async () => {
    const { router, fetchMock } = await openDialog()
    await choose()
    await dialogButton('Run now').trigger('click')
    await settle()
    expect(router.currentRoute.value.fullPath).toBe('/operations/runs/new-run')
    const [call] = startCalls(fetchMock)
    expect((call![1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok-1')
    expect(JSON.parse(String(call![1]?.body))).toEqual({ environment: 'dev', inputs: {} })
  })

  it('sends one request for a double click', async () => {
    const { fetchMock } = await openDialog()
    await choose()
    const target = dialogButton('Run now')
    target.element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    target.element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await settle()
    expect(startCalls(fetchMock)).toHaveLength(1)
  })

  it('keeps one key within an open dialog and takes a new one for the next', async () => {
    const start = () => json(500, { error: { code: 'internal', message: 'Lost' } })
    const { fetchMock } = await openDialog({ start })
    await choose()
    await dialogButton('Run now').trigger('click')
    await settle()
    await dialogButton('Run now').trigger('click')
    await settle()
    const [first, second] = startCalls(fetchMock)
    expect(keyOf(first!)).toMatch(/^[0-9a-f]{32}$/)
    expect(keyOf(second!)).toBe(keyOf(first!))

    await dialogButton('Cancel').trigger('click')
    await settle()
    await button('Run now')
    await settle()
    await choose()
    await dialogButton('Run now').trigger('click')
    await settle()
    expect(keyOf(startCalls(fetchMock)[2]!)).not.toBe(keyOf(first!))
  })

  it('stays open on a duplicate and links to the active run', async () => {
    const start = () =>
      json(409, { error: { code: 'duplicate_run', message: "workflow 'Reconcile' is already running (run a1, key 'workflow')", details: { duplicate_of: 'a1', key: 'workflow' } } })
    const { router } = await openDialog({ start })
    await choose()
    await dialogButton('Run now').trigger('click')
    await settle()
    expect(router.currentRoute.value.path).toBe('/operations')
    const bar = wrapper!.get('.run-now .message-bar')
    expect(bar.text()).toContain('Reconcile is already running, so a second run was not started.')
    expect(bar.text()).not.toContain('key')
    expect(bar.get('a').attributes('href')).toBe('/operations/runs/a1')
  })

  it('reports any other 409 as an error, not as a duplicate', async () => {
    const start = () => json(409, { error: { code: 'conflict', message: 'idempotency key was already used with a different request' } })
    await openDialog({ start })
    await choose()
    await dialogButton('Run now').trigger('click')
    await settle()
    const bar = wrapper!.get('.run-now .message-bar')
    expect(bar.text()).toContain('Idempotency key was already used')
    expect(bar.find('a').exists()).toBe(false)
  })

  it('goes to a queued run, which shows the run ahead of it', async () => {
    const queued = runRow({ id: 'q1', status: 'pending', started_at: null, finished_at: null, trigger_detail: { queued: true, duplicate_of: 'ahead' } })
    const { router } = await openDialog({ start: () => json(200, { run: queued }), run: queued })
    await choose()
    await dialogButton('Run now').trigger('click')
    await settle()
    expect(router.currentRoute.value.fullPath).toBe('/operations/runs/q1')
    expect(wrapper!.get('.message-bar a').attributes('href')).toBe('/operations/runs/ahead')
  })

  it('explains why a workflow cannot run and blocks the button', async () => {
    const runnable = () => json(403, { error: { code: 'forbidden', message: "workflow 'Reconcile' has no promoted version for prod" } })
    const { fetchMock } = await openDialog({ runnable })
    await choose()
    select('Environment').vm.$emit('update:modelValue', 'prod')
    await settle()
    expect(select('Workflow').text()).toContain('No version of this workflow is promoted to prod yet.')
    await dialogButton('Run now').trigger('click')
    await settle()
    expect(startCalls(fetchMock)).toHaveLength(0)
  })

  it.each([
    ['{ not json', 'This is not valid JSON.'],
    ['[1, 2]', 'Inputs must be a JSON object, in braces.'],
    ['null', 'Inputs must be a JSON object, in braces.'],
  ])('refuses the inputs %s inline', async (text, message) => {
    const { fetchMock } = await openDialog()
    await choose()
    wrapper!.findComponent(UTextArea).vm.$emit('update:modelValue', text)
    await settle()
    expect(wrapper!.findComponent(UTextArea).text()).toContain(message)
    await dialogButton('Run now').trigger('click')
    await settle()
    expect(startCalls(fetchMock)).toHaveLength(0)
  })

  it('sends valid inputs', async () => {
    const { fetchMock } = await openDialog()
    await choose()
    wrapper!.findComponent(UTextArea).vm.$emit('update:modelValue', '{"period": "2026-10"}')
    await settle()
    await dialogButton('Run now').trigger('click')
    await settle()
    expect(JSON.parse(String(startCalls(fetchMock)[0]![1]?.body)).inputs).toEqual({ period: '2026-10' })
  })

  it('is a persistent dialog, so a backdrop click keeps what was typed', async () => {
    await openDialog()
    expect(wrapper!.findComponent(UDialog).props('persistent')).toBe(true)
  })

  it('opens from the address the palette command goes to, then forgets it', async () => {
    const { router } = await mountApp('/operations?run=1', { roles: ['operator'] })
    await settle()
    expect(router.currentRoute.value.fullPath).toBe('/operations')
    expect(wrapper!.findComponent(UDialog).props('open')).toBe(true)
  })
})

describe('palette and sidebar', () => {
  const commands = AREAS.flatMap((area) => area.commands)
  const navigation = navigationCommands(AREAS.flatMap((area) => area.navItems))

  it('has Go to runs, Go to schedules and Run now, once each', () => {
    const labels = [...navigation, ...commands].map((command) => command.label)
    for (const label of ['Go to Runs', 'Go to Schedules', 'Run now']) expect(labels.filter((item) => item === label)).toHaveLength(1)
  })

  it('limits Run now to the roles that hold run.trigger', () => {
    const roles = (Object.keys(PERMISSIONS) as Role[]).filter((role) => PERMISSIONS[role].includes('run.trigger'))
    expect(commands.find((command) => command.id === 'operations.run-now')?.roles?.slice().sort()).toEqual(roles.sort())
  })

  it('shows the three screens under Operations', () => {
    const operations = AREAS.flatMap((area) => area.navItems).find((item) => item.id === 'operations')
    expect(operations?.children?.map((child) => child.label)).toEqual(['Dashboard', 'Runs', 'Schedules'])
  })
})

describe('schedules', () => {
  const schedule = {
    id: 'sch1',
    workflow_id: 'w1',
    kind: 'cron',
    name: 'Nightly',
    cron: '0 2 * * *',
    timezone: 'UTC',
    enabled: true,
    token: 'webhook-token-value',
    environment: 'dev',
    next_run_at: '2026-11-06T02:00:00+00:00',
    last_run_at: null,
  }
  const toggleCalls = (fetchMock: FetchMock) => calls(fetchMock, (url) => url.pathname === '/api/schedules/sch1/enabled')

  it('joins the workflow name and never shows a token', async () => {
    await mountApp('/operations/schedules', { roles: ['admin'], schedules: [schedule] })
    await settle()
    expect(wrapper!.get('tbody').text()).toContain('Reconcile')
    expect(wrapper!.get('tbody').text()).toContain('0 2 * * *')
    expect(wrapper!.html()).not.toContain('webhook-token-value')
    expect(client.getQueryData<unknown[]>(['operations', 'schedules'])).not.toContainEqual(expect.objectContaining({ token: expect.anything() }))
  })

  it('shows the switch only to those who may change schedules', async () => {
    await mountApp('/operations/schedules', { roles: ['operator'], schedules: [schedule] })
    expect(wrapper!.findComponent(USwitch).exists()).toBe(false)
    expect(wrapper!.get('tbody').text()).toContain('Enabled')
  })

  it('turns off at once and stays off when the server agrees', async () => {
    const { fetchMock } = await mountApp('/operations/schedules', { roles: ['admin'], schedules: [schedule] })
    wrapper!.findComponent(USwitch).vm.$emit('update:modelValue', false)
    await settle()
    expect(JSON.parse(String(toggleCalls(fetchMock)[0]![1]?.body))).toEqual({ enabled: false })
  })

  it('shows the change first, then rolls back with a toast when the request fails', async () => {
    let refuse: (response: Response) => void = () => undefined
    const toggle = () => new Promise<Response>((done) => (refuse = done)) as unknown as Response
    await mountApp('/operations/schedules', { roles: ['admin'], schedules: [schedule], toggle })
    wrapper!.findComponent(USwitch).vm.$emit('update:modelValue', false)
    await settle()
    expect(wrapper!.findComponent(USwitch).props('modelValue')).toBe(false)
    refuse(json(403, { error: { code: 'forbidden', message: 'no' } }))
    await settle()
    expect(wrapper!.findComponent(USwitch).props('modelValue')).toBe(true)
    expect(document.body.textContent).toContain('You do not have permission to change this schedule.')
  })

  it('says what to do when there are none', async () => {
    await mountApp('/operations/schedules', { roles: ['viewer'] })
    expect(wrapper!.text()).toContain('No schedules yet')
  })
})

describe('shared component gaps', () => {
  const options = [{ value: 'a', label: 'A' }]

  it('USelect ties its help and error text to the combobox', async () => {
    const select = mount(USelect, { props: { label: 'State', options, description: 'Help', error: 'Wrong' } })
    const dropdown = select.get('fluent-dropdown').element
    const control = dropdown.appendChild(document.createElement('div'))
    control.setAttribute('role', 'combobox')
    await select.setProps({ error: 'Still wrong' })
    expect(select.text()).toContain('Help')
    expect(select.text()).toContain('Still wrong')
    expect(control.getAttribute('aria-invalid')).toBe('true')
    const ids = control.getAttribute('aria-describedby')!.split(' ')
    expect(ids.map((id) => select.element.querySelector(`[id="${id}"]`)?.textContent?.trim())).toEqual(['Still wrong', 'Help'])
    await select.setProps({ error: undefined, description: undefined })
    expect(control.hasAttribute('aria-invalid')).toBe(false)
    expect(control.hasAttribute('aria-describedby')).toBe(false)
  })

  it('USelect leaves the same room above its control as a text input', () => {
    const source = readFileSync(resolve(__dirname, '../src/components/USelect.vue'), 'utf8')
    expect(source).toMatch(/\.u-field__label \{[^}]*line-height: var\(--lineHeightBase200\)[^}]*margin-bottom: var\(--spacingVerticalXXS\)/)
    expect(source).toMatch(/\.u-field \{[^}]*gap: var\(--spacingVerticalXXS\)/)
  })

  it('UTextArea gives its help and error text to the inner textarea', async () => {
    const area = mount(UTextArea, { props: { label: 'Inputs', description: 'Help', error: 'Wrong' } })
    const inner = (area.get('fluent-textarea').element as StubTextArea).controlEl
    expect(area.text()).toContain('Wrong')
    expect(inner.getAttribute('aria-invalid')).toBe('true')
    expect(inner.getAttribute('aria-description')).toBe('Wrong Help')
    await area.setProps({ error: undefined, description: undefined })
    expect(inner.hasAttribute('aria-invalid')).toBe(false)
    expect(inner.hasAttribute('aria-description')).toBe(false)
  })

  function clickBackdrop(dialog: VueWrapper): void {
    ;(dialog.get('fluent-dialog').element as StubDialog).inner.click()
  }

  it('UDialog stops a backdrop click only when persistent', () => {
    const persistent = mount(UDialog, { props: { title: 'Edit', persistent: true }, attachTo: document.body })
    clickBackdrop(persistent)
    expect(backdropClick).not.toHaveBeenCalled()
    persistent.unmount()
    const plain = mount(UDialog, { props: { title: 'Edit' }, attachTo: document.body })
    clickBackdrop(plain)
    expect(backdropClick).toHaveBeenCalledOnce()
    plain.unmount()
  })

  it('UDialog leaves clicks inside a persistent dialog alone', async () => {
    const dialog = mount(UDialog, {
      props: { title: 'Edit', persistent: true, open: true },
      slots: { default: '<button id="inner">Inner</button>' },
      attachTo: document.body,
    })
    const heard = vi.fn()
    dialog.get('#inner').element.addEventListener('click', heard)
    await dialog.get('#inner').trigger('click')
    expect(heard).toHaveBeenCalledOnce()
    await dialog.get('[slot="close"]').trigger('click')
    expect(dialog.emitted('update:open')?.at(-1)).toEqual([false])
    dialog.unmount()
  })

  it('UTabs underlines with the accent text colour, which reads on every theme', () => {
    const source = readFileSync(resolve(__dirname, '../src/components/UTabs.vue'), 'utf8')
    expect(source).toContain('border-bottom-color: var(--uaf-accent-text)')
    for (const theme of Object.values(THEMES)) {
      expect(contrastRatio(String(theme.colorBrandForeground1), String(theme.colorNeutralBackground1))).toBeGreaterThanOrEqual(3)
    }
  })
})
