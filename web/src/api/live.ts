// One shared WebSocket for the whole app: opened for the first subscriber, closed after the last.
// Messages carry ids only, so screens refetch what they show (see /events in app/api/system.py).
import { onMounted, onUnmounted, ref, type Ref } from 'vue'

export type LiveEvent = {
  type: string
  run_id?: string
  step_id?: string
  outcome?: string
  status?: string
  message?: string
  workflow?: string
}

type LiveHandler = (event: LiveEvent) => void

const INITIAL_DELAY_MS = 1_000
const MAX_DELAY_MS = 30_000
const POLICY_VIOLATION = 1008
const CONTROL_MESSAGES = new Set(['ping', 'connected'])

const connected = ref(false)
const handlers = new Set<LiveHandler>()
let socket: WebSocket | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryDelay = INITIAL_DELAY_MS

function eventsUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}/api/events`
}

function dispatch(data: unknown): void {
  let event: LiveEvent | null
  try {
    event = JSON.parse(String(data)) as LiveEvent | null
  } catch {
    return
  }
  if (typeof event?.type !== 'string' || CONTROL_MESSAGES.has(event.type)) return
  for (const handler of [...handlers]) handler(event)
}

function scheduleRetry(): void {
  retryTimer = setTimeout(() => {
    retryTimer = null
    connect()
  }, retryDelay)
  retryDelay = Math.min(retryDelay * 2, MAX_DELAY_MS)
}

function connect(): void {
  const current = new WebSocket(eventsUrl())
  socket = current
  current.onopen = () => {
    if (current !== socket) return
    connected.value = true
    retryDelay = INITIAL_DELAY_MS
  }
  current.onmessage = (message) => {
    if (current === socket) dispatch(message.data)
  }
  current.onclose = (event) => {
    if (current !== socket) return
    socket = null
    connected.value = false
    if (event.code !== POLICY_VIOLATION) scheduleRetry()
  }
}

function disconnect(): void {
  if (retryTimer !== null) clearTimeout(retryTimer)
  retryTimer = null
  retryDelay = INITIAL_DELAY_MS
  const current = socket
  socket = null
  connected.value = false
  current?.close()
}

function subscribe(handler: LiveHandler): void {
  handlers.add(handler)
  if (socket === null && retryTimer === null) connect()
}

function unsubscribe(handler: LiveHandler): void {
  handlers.delete(handler)
  if (handlers.size === 0) disconnect()
}

/** Receive live events while the calling component is mounted. `connected` is shared by all callers. */
export function useLiveEvents(handler: LiveHandler): { connected: Ref<boolean> } {
  onMounted(() => subscribe(handler))
  onUnmounted(() => unsubscribe(handler))
  return { connected }
}
