<script setup lang="ts">
// The Operations dashboard: plain counts that link to what is behind them, what failed, and what ran
// last. `?run=1` opens Run now: a palette command can only navigate, and the shell cannot host it.
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import RelativeTime from '@/components/RelativeTime.vue'
import AppPage from '@/components/shell/AppPage.vue'
import MessageBar from '@/components/shell/MessageBar.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import UButton from '@/components/UButton.vue'
import { formatCount } from '@/format'
import { useSession } from '@/stores/session'
import { fetchDashboard, fetchFailedRuns, operationsKeys } from './api'
import { titleCase, type Dashboard, type DashboardRun, type RunSummary } from './model'
import RunNowDialog from './RunNowDialog.vue'
import { useOperationsLive } from './useOperationsLive'

const ATTENTION_LIMIT = 5

const route = useRoute()
const router = useRouter()
const session = useSession()
const live = useOperationsLive()

const canRun = computed(() => session.permissions.includes('run.trigger'))
const runNowOpen = ref(false)

const dashboard = useQuery(
  computed(() => ({
    queryKey: operationsKeys.dashboard,
    queryFn: ({ signal }: { signal: AbortSignal }) => fetchDashboard(signal),
    refetchInterval: live.pollEvery((data: Dashboard) => data.running + data.waiting > 0),
  })),
)
const failedRuns = useQuery(
  computed(() => ({
    queryKey: operationsKeys.attention,
    queryFn: ({ signal }: { signal: AbortSignal }) => fetchFailedRuns(ATTENTION_LIMIT, signal),
    refetchInterval: live.pollEvery<RunSummary[]>(),
  })),
)

const runsLink = (...status: string[]): RouteLocationRaw => ({ name: 'operations.runs', query: { status } })

const numbers = computed(() => {
  const data = dashboard.data.value
  if (!data) return []
  return [
    // The dashboard's "running" includes pending runs, so its link must too.
    { key: 'running', label: 'Running', value: data.running, to: runsLink('pending', 'running') },
    { key: 'waiting', label: 'Waiting', value: data.waiting, to: runsLink('suspended') },
    { key: 'failed', label: 'Failed', value: data.failed, to: runsLink('failed') },
    { key: 'open', label: 'Open tasks', value: data.openTasks, to: '/inbox' },
    { key: 'overdue', label: 'Overdue tasks', value: data.overdueTasks, to: '/inbox' },
  ]
})

const columns: DataTableColumn[] = [
  { key: 'status', label: 'Status', width: '14ch' },
  { key: 'workflowName', label: 'Workflow' },
  { key: 'environment', label: 'Environment', width: '12ch' },
  { key: 'trigger', label: 'Trigger', width: '12ch' },
  { key: 'createdAt', label: 'Started', width: '14ch' },
]

const openRun = (row: DashboardRun) => router.push({ name: 'operations.run', params: { runId: row.id } })

watch(
  () => route.query.run,
  (value) => {
    if (value === undefined) return
    if (canRun.value) runNowOpen.value = true
    void router.replace({ query: {} })
  },
  { immediate: true },
)
</script>

<template>
  <AppPage title="Dashboard" subtitle="What is running, what is waiting and what needs you.">
    <template v-if="canRun" #actions>
      <UButton appearance="primary" icon="play" @click="runNowOpen = true">Run now</UButton>
    </template>
    <template v-if="live.paused.value" #messages>
      <MessageBar>Live updates paused. This page keeps refreshing every few seconds.</MessageBar>
    </template>

    <LoadState :loading="dashboard.isPending.value" :error="dashboard.data.value ? null : dashboard.error.value" @retry="dashboard.refetch()">
      <div class="dashboard">
        <dl class="numbers">
          <div v-for="item in numbers" :key="item.key" class="numbers__item">
            <dt>{{ item.label }}</dt>
            <dd>
              <RouterLink class="numbers__value" :to="item.to" :aria-label="`${formatCount(item.value)} ${item.label.toLowerCase()}`">
                {{ formatCount(item.value) }}
              </RouterLink>
            </dd>
          </div>
        </dl>

        <section aria-labelledby="attention-title">
          <div class="section-head">
            <h2 id="attention-title">Needs attention</h2>
            <RouterLink v-if="failedRuns.data.value?.length" :to="runsLink('failed')">All failed runs</RouterLink>
          </div>
          <LoadState
            :loading="failedRuns.isPending.value"
            :error="failedRuns.data.value ? null : failedRuns.error.value"
            @retry="failedRuns.refetch()"
          >
            <EmptyState
              v-if="!failedRuns.data.value?.length"
              title="Nothing needs attention"
              description="Failed runs appear here so you can open and retry them."
              :heading-level="3"
            />
            <ul v-else class="attention">
              <li v-for="run in failedRuns.data.value" :key="run.id" class="attention__item">
                <StatusBadge :status="run.status" />
                <RouterLink class="attention__name" :to="{ name: 'operations.run', params: { runId: run.id } }">
                  {{ run.workflowName }}
                </RouterLink>
                <span class="attention__error" :title="run.error">{{ run.error }}</span>
                <RelativeTime class="quiet" :value="run.finishedAt ?? run.createdAt" />
              </li>
            </ul>
          </LoadState>
        </section>

        <section aria-labelledby="recent-title">
          <div class="section-head">
            <h2 id="recent-title">Recent runs</h2>
            <RouterLink v-if="dashboard.data.value?.recentRuns.length" :to="{ name: 'operations.runs' }">All runs</RouterLink>
          </div>
          <EmptyState
            v-if="!dashboard.data.value?.recentRuns.length"
            title="No runs yet"
            :description="canRun ? 'Use Run now to start a workflow.' : 'Runs appear here once a workflow starts.'"
            :heading-level="3"
          />
          <DataTable
            v-else
            :columns="columns"
            :rows="dashboard.data.value.recentRuns"
            :row-key="(row) => row.id"
            :row-label="(row) => `${row.workflowName}, ${row.status}`"
            caption="Recent runs"
            @row-open="openRun"
          >
            <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
            <template #cell-trigger="{ row }">{{ titleCase(row.trigger) }}</template>
            <template #cell-createdAt="{ row }"><RelativeTime :value="row.createdAt" /></template>
          </DataTable>
        </section>
      </div>
    </LoadState>

    <RunNowDialog v-if="canRun" v-model:open="runNowOpen" />
  </AppPage>
</template>

<style scoped>
.dashboard {
  display: grid;
  gap: var(--space-24);
  min-width: 0;
}
.numbers {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-12) var(--space-32);
  margin: 0;
}
.numbers__item {
  display: flex;
  flex-direction: column-reverse;
}
.numbers__item dt {
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
  line-height: var(--line-height-16);
}
.numbers__item dd {
  margin: 0;
}
.numbers__value {
  color: var(--uaf-text);
  font-size: var(--font-size-24);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
  line-height: var(--line-height-32);
  text-decoration: none;
}
.numbers__value:hover {
  color: var(--uaf-accent-text);
  text-decoration: underline;
}
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-12);
  margin-bottom: var(--space-8);
}
.section-head h2 {
  font-size: var(--font-size-16);
  line-height: var(--line-height-22);
}
.quiet {
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
  white-space: nowrap;
}
.attention {
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: var(--stroke-1) solid var(--uaf-border);
}
/* Each row is its own grid, so the columns are fixed to line up. */
.attention__item {
  display: grid;
  grid-template-columns: 12ch minmax(0, 2fr) minmax(0, 3fr) 9ch;
  align-items: center;
  gap: var(--space-12);
  min-height: var(--uaf-row-height);
  padding: var(--uaf-cell-padding);
  border-bottom: var(--stroke-1) solid var(--uaf-border);
}
.attention__name {
  overflow-wrap: anywhere;
}
.attention__error {
  overflow: hidden;
  color: var(--uaf-text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
