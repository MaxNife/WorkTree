<script setup lang="ts">
// Schedules and triggers. Turning one on or off shows at once and undoes itself if the server says no.
// Webhook tokens are not read from the API's answer, so no state here can show one.
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import LoadState from '@/components/LoadState.vue'
import RelativeTime from '@/components/RelativeTime.vue'
import WorkflowFlower from '@/components/WorkflowFlower.vue'
import AppPage from '@/components/shell/AppPage.vue'
import MessageBar from '@/components/shell/MessageBar.vue'
import USwitch from '@/components/USwitch.vue'
import { formatDateTime } from '@/format'
import { useSession } from '@/stores/session'
import { useToast } from '@/stores/toast'
import { actionError, fetchSchedules, fetchWorkflows, operationsKeys, setScheduleEnabled } from './api'
import { titleCase, type Schedule } from './model'
import { useOperationsLive } from './useOperationsLive'

const queryClient = useQueryClient()
const session = useSession()
const toast = useToast()
const live = useOperationsLive()

const canChange = computed(() => session.permissions.includes('admin.schedules'))

const schedules = useQuery(
  computed(() => ({
    queryKey: operationsKeys.schedules,
    queryFn: ({ signal }: { signal: AbortSignal }) => fetchSchedules(signal),
    refetchInterval: live.pollEvery<Schedule[]>(),
  })),
)
// Schedules carry only a workflow id.
const workflows = useQuery({ queryKey: operationsKeys.workflows, queryFn: ({ signal }) => fetchWorkflows(signal) })
const workflowNames = computed(() => new Map((workflows.data.value ?? []).map((row) => [row.id, row.name])))
const workflowName = (schedule: Schedule): string => workflowNames.value.get(schedule.workflowId) ?? schedule.workflowId

const columns: DataTableColumn[] = [
  { key: 'workflow', label: 'Workflow' },
  { key: 'kind', label: 'Kind', width: '11ch' },
  { key: 'cron', label: 'Cron and timezone' },
  { key: 'nextRunAt', label: 'Next run', width: '24ch' },
  { key: 'lastRunAt', label: 'Last run', width: '12ch' },
  { key: 'enabled', label: 'Enabled', width: '10ch' },
]

function setLocal(id: string, enabled: boolean): void {
  queryClient.setQueryData<Schedule[]>(operationsKeys.schedules, (rows) =>
    rows?.map((row) => (row.id === id ? { ...row, enabled } : row)),
  )
}

const toggle = useMutation({
  mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => setScheduleEnabled(id, enabled),
  onMutate: async ({ id, enabled }) => {
    // A refetch already on its way must not overwrite this with the old value.
    await queryClient.cancelQueries({ queryKey: operationsKeys.schedules })
    setLocal(id, enabled)
  },
  onError: (error, { id, enabled }) => {
    setLocal(id, !enabled)
    toast.error(actionError(error, 'change this schedule'))
  },
  onSettled: () => queryClient.invalidateQueries({ queryKey: operationsKeys.schedules }),
})
</script>

<template>
  <AppPage title="Schedules" subtitle="What starts workflows without anyone pressing Run now." band="hibiscus">
    <template v-if="live.paused.value" #messages>
      <MessageBar>Live updates paused. This page keeps refreshing every few seconds.</MessageBar>
    </template>
    <LoadState
      :loading="schedules.isPending.value"
      :error="schedules.data.value ? null : schedules.error.value"
      :empty="schedules.data.value?.length === 0"
      empty-title="No schedules yet"
      empty-description="Add a schedule to a workflow in the Studio to see it here."
      @retry="schedules.refetch()"
    >
      <DataTable class="schedules" :columns="columns" :rows="schedules.data.value ?? []" :row-key="(row) => row.id" caption="Schedules">
        <template #cell-workflow="{ row }">
          <RouterLink class="workflow-cell" :to="{ name: 'studio.workflow', params: { workflowId: row.workflowId } }">
            <WorkflowFlower :id="row.workflowId" :size="18" />{{ workflowName(row) }}
          </RouterLink>
          <span v-if="row.name" class="quiet schedule-name">{{ row.name }}</span>
        </template>
        <template #cell-kind="{ row }">{{ titleCase(row.kind) }}</template>
        <template #cell-cron="{ row }">
          <template v-if="row.cron">
            <code class="cron">{{ row.cron }}</code> <span class="quiet">{{ row.timezone }}</span>
          </template>
          <template v-else>-</template>
        </template>
        <template #cell-nextRunAt="{ row }">{{ formatDateTime(row.nextRunAt) }}</template>
        <template #cell-lastRunAt="{ row }"><RelativeTime :value="row.lastRunAt" /></template>
        <template #cell-enabled="{ row }">
          <USwitch
            v-if="canChange"
            class="schedules__switch"
            :label="`Enable ${workflowName(row)}`"
            :model-value="row.enabled"
            @update:model-value="toggle.mutate({ id: row.id, enabled: $event })"
          />
          <template v-else>{{ row.enabled ? 'Enabled' : 'Disabled' }}</template>
        </template>
      </DataTable>
    </LoadState>
  </AppPage>
</template>

<style scoped>
.schedules :deep(td) {
  overflow-wrap: anywhere;
}
/* The column says what it is: each switch keeps its own name for screen readers. */
.schedules__switch :deep(.u-toggle__label) {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.schedule-name {
  margin-inline-start: var(--space-8);
}
.cron {
  font-family: var(--wt-font-mono);
  font-size: var(--font-size-12);
}
.quiet {
  color: var(--wt-muted);
  font-size: var(--font-size-12);
}
.workflow-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
}
</style>
