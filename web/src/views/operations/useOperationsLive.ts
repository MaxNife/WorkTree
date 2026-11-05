// What keeps an Operations screen current. There are no run-started or step-started events, so events
// alone cannot be trusted: a screen also polls while it shows an active run or while the socket is down.
import { useQueryClient } from '@tanstack/vue-query'
import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { ApiError } from '@/api/client'
import { useLiveEvents, type LiveEvent } from '@/api/live'
import { operationsKeys } from './api'

export const POLL_MS = 3_000
const PAUSED_AFTER_MS = 10_000
// A run can finish many steps at once: one refetch answers them all.
const COALESCE_MS = 200

/** The part of a vue-query Query that decides whether to poll. */
interface PolledQuery<T> {
  state: { data: T | undefined; error: unknown }
}

export interface OperationsLive {
  /** True once the socket has been down for long enough to say so. */
  paused: Ref<boolean>
  /**
   * The `refetchInterval` for a query. Call it inside the query's reactive options, so that a socket
   * drop reaches a query whose data will not change. `isActive` looks at the data on screen; without
   * it the query polls only while the socket is down.
   */
  pollEvery: <T>(isActive?: (data: T) => boolean) => (query: PolledQuery<T>) => number | false
}

export function useOperationsLive(): OperationsLive {
  const queryClient = useQueryClient()
  const runIds = new Set<string>()
  let flushTimer: ReturnType<typeof setTimeout> | undefined

  function flush(): void {
    flushTimer = undefined
    const keys = [operationsKeys.dashboard, operationsKeys.attention, operationsKeys.runs, operationsKeys.schedules]
    for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey })
    for (const runId of runIds) void queryClient.invalidateQueries({ queryKey: operationsKeys.run(runId) })
    runIds.clear()
  }

  function onEvent(event: LiveEvent): void {
    if (event.type !== 'step.completed' && event.type !== 'run.finished') return
    if (event.run_id) runIds.add(event.run_id)
    flushTimer ??= setTimeout(flush, COALESCE_MS)
  }

  const { connected } = useLiveEvents(onEvent)
  const paused = ref(false)
  let pausedTimer: ReturnType<typeof setTimeout> | undefined

  watch(
    connected,
    (isConnected) => {
      clearTimeout(pausedTimer)
      if (isConnected) paused.value = false
      else
        pausedTimer = setTimeout(() => {
          paused.value = true
        }, PAUSED_AFTER_MS)
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    clearTimeout(pausedTimer)
    clearTimeout(flushTimer)
  })

  function pollEvery<T>(isActive?: (data: T) => boolean) {
    const socketDown = !connected.value
    return (query: PolledQuery<T>): number | false => {
      // A signed-out, forbidden or missing resource stays that way.
      if (query.state.error instanceof ApiError && query.state.error.status < 500) return false
      const data = query.state.data
      return socketDown || (data !== undefined && isActive?.(data)) ? POLL_MS : false
    }
  }

  return { paused, pollEvery }
}
