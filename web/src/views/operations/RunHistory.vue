<script setup lang="ts">
// Every run, with its filters, sort and page in the URL so a view can be shared and survives reload.
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import FilterBar from '@/components/FilterBar.vue'
import LoadState from '@/components/LoadState.vue'
import RelativeTime from '@/components/RelativeTime.vue'
import AppPage from '@/components/shell/AppPage.vue'
import MessageBar from '@/components/shell/MessageBar.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import UPagination from '@/components/UPagination.vue'
import USelect from '@/components/USelect.vue'
import { formatDuration, statusStyle } from '@/status'
import { fetchRuns, operationsKeys } from './api'
import { hasActiveFilters, PAGE_SIZE, readRunFilters, RUN_STATUSES, TIME_RANGES, writeRunFilters, type RunFilters } from './filters'
import { elapsedMs, ENVIRONMENTS, isActive, titleCase, TRIGGERS, type RunPage, type RunSummary } from './model'
import { useOperationsLive } from './useOperationsLive'

const route = useRoute()
const router = useRouter()
const live = useOperationsLive()

const filters = computed(() => readRunFilters(route.query))
const filtered = computed(() => hasActiveFilters(filters.value))

/** Any change but a change of page goes back to the first page. */
function update(change: Partial<RunFilters>): void {
  const next = { ...filters.value, offset: 0, ...change }
  void router.replace({ query: writeRunFilters(next) })
}

const runs = useQuery(
  computed(() => {
    const current = filters.value
    return {
      queryKey: operationsKeys.runList(current),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchRuns(current, PAGE_SIZE, signal),
      placeholderData: keepPreviousData,
      refetchInterval: live.pollEvery((data: RunPage) => data.items.some((run) => isActive(run.status))),
    }
  }),
)

// A shared link can point past the end once the list has shrunk.
watch(runs.data, (data) => {
  if (data && !runs.isPlaceholderData.value && data.items.length === 0 && filters.value.offset > 0) update({ offset: 0 })
})

const columns: DataTableColumn[] = [
  { key: 'status', label: 'Status', sortable: true, width: '13ch' },
  { key: 'workflow_name', label: 'Workflow', sortable: true },
  { key: 'environment', label: 'Environment', sortable: true, width: '13ch' },
  { key: 'trigger', label: 'Trigger', width: '11ch' },
  { key: 'requestedBy', label: 'Requested by', width: '16ch' },
  { key: 'created_at', label: 'Started', sortable: true, width: '14ch' },
  { key: 'duration', label: 'Duration', align: 'end', width: '10ch' },
]

const options = (all: string, values: readonly string[], label: (value: string) => string) => [
  { value: '', label: all },
  ...values.map((value) => ({ value, label: label(value) })),
]

const statusOptions = [
  { value: '', label: 'All statuses' },
  // Together, as the dashboard counts them.
  { value: 'pending,running', label: 'Running or pending' },
  ...RUN_STATUSES.map((value) => ({ value, label: statusStyle(value).label })),
]
const environmentOptions = options('All environments', ENVIRONMENTS, (value) => value)
const triggerOptions = options('All triggers', TRIGGERS, titleCase)
const rangeOptions = TIME_RANGES.map(({ value, label }) => ({ value, label }))

const sort = computed({
  get: () => filters.value.sort,
  set: (value: string) => update({ sort: value }),
})
const offset = computed({
  get: () => filters.value.offset,
  set: (value: number) => update({ offset: value }),
})

function clear(): void {
  void router.replace({ query: writeRunFilters({ ...readRunFilters({}), sort: filters.value.sort }) })
}

const openRun = (row: RunSummary) => router.push({ name: 'operations.run', params: { runId: row.id } })
</script>

<template>
  <AppPage title="Runs" subtitle="Every run of every workflow.">
    <template v-if="live.paused.value" #messages>
      <MessageBar>Live updates paused. This page keeps refreshing every few seconds.</MessageBar>
    </template>
    <template #commands>
      <FilterBar
        :search="filters.q"
        search-label="Search runs"
        :active="filtered"
        @update:search="update({ q: $event })"
        @clear="clear"
      >
        <USelect
          label="Status"
          :model-value="filters.status.join(',')"
          :options="statusOptions"
          @update:model-value="update({ status: $event ? $event.split(',') : [] })"
        />
        <USelect
          label="Environment"
          :model-value="filters.environment"
          :options="environmentOptions"
          @update:model-value="update({ environment: $event })"
        />
        <USelect
          label="Trigger"
          :model-value="filters.trigger"
          :options="triggerOptions"
          @update:model-value="update({ trigger: $event })"
        />
        <USelect
          label="Time range"
          :model-value="filters.range"
          :options="rangeOptions"
          @update:model-value="update({ range: $event })"
        />
      </FilterBar>
    </template>

    <LoadState
      :loading="runs.isPending.value"
      :error="runs.data.value ? null : runs.error.value"
      :empty="runs.data.value?.total === 0"
      :empty-title="filtered ? 'No matching runs' : 'No runs yet'"
      :empty-description="filtered ? 'Change or clear the filters to see more runs.' : 'Start a workflow from the dashboard to see it here.'"
      @retry="runs.refetch()"
    >
      <div class="runs">
        <DataTable
          v-model:sort="sort"
          :columns="columns"
          :rows="runs.data.value?.items ?? []"
          :row-key="(row) => row.id"
          :row-label="(row) => `${row.workflowName}, ${row.status}`"
          caption="Runs"
          @row-open="openRun"
        >
          <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
          <template #cell-workflow_name="{ row }">{{ row.workflowName }}</template>
          <template #cell-trigger="{ row }">{{ titleCase(row.trigger) }}</template>
          <template #cell-created_at="{ row }">
            <RelativeTime v-if="row.startedAt" :value="row.startedAt" />
            <span v-else class="quiet">Not started</span>
          </template>
          <template #cell-duration="{ row }">
            <span class="duration">{{ formatDuration(elapsedMs(row.startedAt, row.finishedAt)) }}</span>
          </template>
        </DataTable>
        <UPagination v-model:offset="offset" :total="runs.data.value?.total ?? 0" :limit="PAGE_SIZE" />
      </div>
    </LoadState>
  </AppPage>
</template>

<style scoped>
.runs {
  display: grid;
  gap: var(--spacingVerticalS);
  min-width: 0;
}
.runs :deep(td) {
  overflow-wrap: anywhere;
}
.duration {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.quiet {
  color: var(--uaf-text-muted);
}
</style>
