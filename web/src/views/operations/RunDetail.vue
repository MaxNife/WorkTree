<script setup lang="ts">
// One run, GitHub Actions style: the step list with a properties column beside it. Logs are masked by
// the API and shown as they arrive; nothing here reconstructs a masked value.
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadState from '@/components/LoadState.vue'
import PropertyList, { type PropertyItem } from '@/components/PropertyList.vue'
import RelativeTime from '@/components/RelativeTime.vue'
import RunTimeline, { type TimelineStep } from '@/components/RunTimeline.vue'
import { useCrumbLabel } from '@/components/shell/breadcrumbs'
import AppPage from '@/components/shell/AppPage.vue'
import MessageBar from '@/components/shell/MessageBar.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import UButton from '@/components/UButton.vue'
import UTabs from '@/components/UTabs.vue'
import { formatDateTime } from '@/format'
import { formatDuration } from '@/status'
import { useSession } from '@/stores/session'
import { useToast } from '@/stores/toast'
import { actionError, cancelRun, fetchRun, operationsKeys, retryRun, sentence } from './api'
import { elapsedMs, formatBytes, isActive, titleCase, type RunDetail, type RunStep } from './model'
import RunStepDetail from './RunStepDetail.vue'
import { useOperationsLive } from './useOperationsLive'

const TABS = ['steps', 'artifacts', 'incidents'] as const

const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const session = useSession()
const toast = useToast()
const live = useOperationsLive()

const runId = computed(() => String(route.params.runId))

const detail = useQuery(
  computed(() => {
    const id = runId.value
    return {
      queryKey: operationsKeys.run(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchRun(id, signal),
      refetchInterval: live.pollEvery((data: RunDetail) => isActive(data.status)),
    }
  }),
)
const run = computed(() => detail.data.value)
const loadError = computed(() => {
  const error = detail.error.value
  if (run.value || !error) return null
  if (error instanceof ApiError && error.status === 404) return 'This run does not exist.'
  return error instanceof Error ? sentence(error.message) : 'The run could not be loaded.'
})
useCrumbLabel(() => run.value?.workflowName)

const canAct = computed(() => session.permissions.includes('run.retry'))
const canRetry = computed(() => canAct.value && run.value?.status === 'failed')
const canCancel = computed(() => canAct.value && isActive(run.value?.status ?? ''))

const tab = computed({
  get: () => (TABS as readonly unknown[]).includes(route.query.tab) ? String(route.query.tab) : 'steps',
  set: (value: string) => void router.replace({ query: value === 'steps' ? {} : { tab: value } }),
})
const tabs = computed(() => [
  { id: 'steps', label: 'Steps', count: run.value?.steps.length ?? 0 },
  { id: 'artifacts', label: 'Artifacts', count: run.value?.artifacts.length ?? 0 },
  { id: 'incidents', label: 'Incidents', count: run.value?.incidents.length ?? 0 },
])

function stepName(step: RunStep): string {
  return step.foreachCount > 0 ? `${step.stepId} (item ${step.iteration + 1} of ${step.foreachCount})` : step.stepId
}

const steps = computed<TimelineStep[]>(() =>
  (run.value?.steps ?? []).map((step) => ({
    id: step.id,
    name: stepName(step),
    state: step.state,
    durationMs: step.finishedAt ? step.durationMs : elapsedMs(step.startedAt, null),
    attempts: Math.max(step.attempts.length, step.attempt),
    message: step.message,
  })),
)
const stepById = computed(() => new Map((run.value?.steps ?? []).map((step) => [step.id, step])))

const queuedBehind = computed(() => (run.value?.status === 'pending' ? run.value.queuedBehind : null))
const failureMessage = computed(() => (run.value?.status === 'failed' ? run.value.error : ''))

const properties = computed<PropertyItem[]>(() => {
  const current = run.value
  if (!current) return []
  return [
    { key: 'workflow', label: 'Workflow', value: current.workflowName },
    { key: 'version', label: 'Version', value: current.version },
    { key: 'environment', label: 'Environment', value: current.environment },
    { key: 'trigger', label: 'Trigger', value: titleCase(current.trigger) },
    { key: 'requestedBy', label: 'Requested by', value: current.requestedBy },
    { key: 'started', label: 'Started', value: formatDateTime(current.startedAt) },
    { key: 'finished', label: 'Finished', value: formatDateTime(current.finishedAt) },
    { key: 'duration', label: 'Duration', value: formatDuration(elapsedMs(current.startedAt, current.finishedAt)) },
    { key: 'correlation', label: 'Correlation id', value: current.correlationId },
    { key: 'parent', label: 'Parent run', value: current.parentRunId },
  ]
})

const artifactColumns: DataTableColumn[] = [
  { key: 'name', label: 'Name' },
  { key: 'stepId', label: 'Step', width: '20ch' },
  { key: 'size', label: 'Size', align: 'end', width: '10ch' },
  { key: 'createdAt', label: 'Created', width: '12ch' },
  { key: 'download', label: 'Download', width: '10ch' },
]
const incidentColumns: DataTableColumn[] = [
  { key: 'kind', label: 'Kind', width: '16ch' },
  { key: 'stepId', label: 'Step', width: '20ch' },
  { key: 'message', label: 'Message' },
  { key: 'state', label: 'State', width: '10ch' },
  { key: 'createdAt', label: 'Raised', width: '12ch' },
]

const artifactUrl = (artifactId: string): string => `/api/artifacts/${encodeURIComponent(artifactId)}/download`

const refresh = () => queryClient.invalidateQueries({ queryKey: operationsKeys.all })

const retry = useMutation({
  mutationFn: () => retryRun(runId.value),
  onSuccess: () => {
    toast.success('Retrying from the failed step.')
    void refresh()
  },
  onError: (error) => toast.error(actionError(error, 'retry this run')),
})

const confirmCancel = ref(false)
const cancel = useMutation({
  mutationFn: () => cancelRun(runId.value),
  onSuccess: () => {
    toast.success('The run was cancelled.')
    void refresh()
  },
  onError: (error) => toast.error(actionError(error, 'cancel this run')),
  onSettled: () => {
    confirmCancel.value = false
  },
})

watch(runId, () => {
  confirmCancel.value = false
})
</script>

<template>
  <AppPage :title="run?.workflowName || 'Run'" :subtitle="run ? run.id : undefined">
    <template v-if="run" #actions>
      <StatusBadge class="run-status" :status="run.status" />
      <UButton v-if="canCancel" icon="stop" @click="confirmCancel = true">Cancel</UButton>
      <UButton v-if="canRetry" appearance="primary" icon="retry" :loading="retry.isPending.value" @click="retry.mutate()">
        Retry from failed step
      </UButton>
    </template>
    <template v-if="live.paused.value || queuedBehind || failureMessage" #messages>
      <MessageBar v-if="live.paused.value">Live updates paused. This page keeps refreshing every few seconds.</MessageBar>
      <MessageBar v-if="queuedBehind" title="Queued">
        This run starts when the run ahead of it finishes.
        <template #actions>
          <RouterLink :to="{ name: 'operations.run', params: { runId: queuedBehind } }">Open the active run</RouterLink>
        </template>
      </MessageBar>
      <MessageBar v-if="failureMessage" intent="error">{{ failureMessage }}</MessageBar>
    </template>

    <LoadState :loading="detail.isPending.value" :error="loadError" @retry="detail.refetch()">
      <div v-if="run" class="detail">
        <div class="detail__main">
          <UTabs v-model="tab" :tabs="tabs" label="Run sections" />

          <!-- Hidden, not removed: the steps someone opened stay open when they come back. -->
          <div v-show="tab === 'steps'" role="tabpanel" aria-label="Steps">
            <RunTimeline :steps="steps">
              <template #detail="{ step }">
                <RunStepDetail
                  v-if="stepById.get(step.id)"
                  :step="stepById.get(step.id)!"
                  :name="step.name"
                  :incidents="run.incidents"
                />
              </template>
            </RunTimeline>
          </div>

          <div v-if="tab === 'artifacts'" role="tabpanel" aria-label="Artifacts">
            <EmptyState
              v-if="run.artifacts.length === 0"
              title="No artifacts"
              description="Files that the steps of this run save appear here."
              :heading-level="2"
            />
            <DataTable v-else :columns="artifactColumns" :rows="run.artifacts" :row-key="(row) => row.id" caption="Artifacts">
              <template #cell-size="{ row }">{{ formatBytes(row.bytes) }}</template>
              <template #cell-createdAt="{ row }"><RelativeTime :value="row.createdAt" /></template>
              <template #cell-download="{ row }">
                <a :href="artifactUrl(row.id)" :aria-label="`Download ${row.name}`" download>Download</a>
              </template>
            </DataTable>
          </div>

          <div v-if="tab === 'incidents'" role="tabpanel" aria-label="Incidents">
            <EmptyState
              v-if="run.incidents.length === 0"
              title="No incidents"
              description="Anything that stops a step of this run appears here."
              :heading-level="2"
            />
            <DataTable v-else :columns="incidentColumns" :rows="run.incidents" :row-key="(row) => row.id" caption="Incidents">
              <template #cell-kind="{ row }">{{ titleCase(row.kind) }}</template>
              <template #cell-state="{ row }">{{ row.resolved ? 'Resolved' : 'Open' }}</template>
              <template #cell-createdAt="{ row }"><RelativeTime :value="row.createdAt" /></template>
            </DataTable>
          </div>
        </div>

        <aside class="detail__side" aria-label="Run properties">
          <PropertyList :items="properties">
            <template #parent>
              <RouterLink v-if="run.parentRunId" :to="{ name: 'operations.run', params: { runId: run.parentRunId } }">
                {{ run.parentRunId }}
              </RouterLink>
              <template v-else>-</template>
            </template>
          </PropertyList>
        </aside>
      </div>
    </LoadState>

    <ConfirmDialog
      v-model:open="confirmCancel"
      title="Cancel this run?"
      message="Steps that have finished stay finished. Steps still to come do not run."
      confirm-label="Cancel run"
      danger
      :busy="cancel.isPending.value"
      @confirm="cancel.mutate()"
    />
  </AppPage>
</template>

<style scoped>
.detail {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--space-16) var(--space-20);
}
.detail__main {
  display: grid;
  flex: 1 1 440px;
  gap: var(--space-12);
  min-width: 0;
}
.detail__side {
  flex: 0 1 280px;
  min-width: 0;
}
.detail__main :deep(td) {
  overflow-wrap: anywhere;
}
.run-status {
  margin-inline-end: var(--space-8);
}
</style>
