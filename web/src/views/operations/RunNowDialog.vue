<script setup lang="ts">
// Start a run. One Idempotency-Key per open, so a repeated click or a retry after a lost response
// starts one run. The duplicate guard is an expected answer, not a failure: see `start_run`.
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import LoadState from '@/components/LoadState.vue'
import MessageBar from '@/components/shell/MessageBar.vue'
import UButton from '@/components/UButton.vue'
import UDialog from '@/components/UDialog.vue'
import USelect from '@/components/USelect.vue'
import UTextArea from '@/components/UTextArea.vue'
import { actionError, fetchRunnableVersion, fetchWorkflows, newIdempotencyKey, operationsKeys, sentence, startRun } from './api'
import { ENVIRONMENTS } from './model'

const open = defineModel<boolean>('open', { default: false })

const router = useRouter()
const queryClient = useQueryClient()

const workflowId = ref('')
const environment = ref('dev')
const inputsText = ref('')
const failure = ref('')
const duplicate = ref<{ runId: string; message: string } | null>(null)
let idempotencyKey = ''
// Plain, not `isPending`: that updates a tick later, and this has to stop a second click at once.
let submitting = false

const workflows = useQuery({
  queryKey: operationsKeys.workflows,
  queryFn: ({ signal }) => fetchWorkflows(signal),
  enabled: open,
})
const workflowOptions = computed(() => (workflows.data.value ?? []).map((row) => ({ value: row.id, label: row.name })))
const environmentOptions = ENVIRONMENTS.map((name) => ({ value: name, label: name }))

// "Cannot run" is an answer here, so it is neither retried nor kept for long.
const runnable = useQuery({
  queryKey: computed(() => operationsKeys.runnable(workflowId.value, environment.value)),
  queryFn: ({ signal }) => fetchRunnableVersion(workflowId.value, environment.value, signal),
  enabled: computed(() => open.value && Boolean(workflowId.value)),
  retry: false,
  staleTime: 0,
})
const cannotRun = computed(() => {
  const error = runnable.error.value
  if (!error) return ''
  // The API refuses only production, and only until a version has been promoted there.
  if (error instanceof ApiError && error.status === 403) return `No version of this workflow is promoted to ${environment.value} yet.`
  if (error instanceof ApiError && error.status === 404) return 'This workflow no longer exists.'
  return error.message ? sentence(error.message) : 'This workflow cannot run in that environment.'
})
const versionNote = computed(() => {
  if (!workflowId.value || cannotRun.value || typeof runnable.data.value !== 'number') return undefined
  return `Runs version ${runnable.data.value}.`
})

const parsedInputs = computed<{ value?: Record<string, unknown>; error?: string }>(() => {
  if (!inputsText.value.trim()) return { value: {} }
  try {
    const value: unknown = JSON.parse(inputsText.value)
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) return { value: value as Record<string, unknown> }
    return { error: 'Inputs must be a JSON object, in braces.' }
  } catch {
    return { error: 'This is not valid JSON.' }
  }
})

const start = useMutation({
  mutationFn: () =>
    startRun(workflowId.value, { environment: environment.value, inputs: parsedInputs.value.value ?? {} }, idempotencyKey),
})

const canSubmit = computed(
  () => Boolean(workflowId.value) && !cannotRun.value && !parsedInputs.value.error && runnable.isSuccess.value,
)

async function submit(): Promise<void> {
  if (!canSubmit.value || submitting) return
  submitting = true
  failure.value = ''
  duplicate.value = null
  try {
    const result = await start.mutateAsync()
    if (result.kind === 'duplicate') {
      const name = workflows.data.value?.find((row) => row.id === workflowId.value)?.name ?? 'This workflow'
      duplicate.value = { runId: result.activeRunId, message: `${name} is already running, so a second run was not started.` }
      return
    }
    void queryClient.invalidateQueries({ queryKey: operationsKeys.all })
    open.value = false
    await router.push({ name: 'operations.run', params: { runId: result.run.id } })
  } catch (error) {
    failure.value = actionError(error, 'start this run')
  } finally {
    submitting = false
  }
}

function reset(): void {
  idempotencyKey = newIdempotencyKey()
  workflowId.value = ''
  environment.value = 'dev'
  inputsText.value = ''
  failure.value = ''
  duplicate.value = null
}

watch(
  open,
  (isOpen) => {
    if (isOpen) reset()
  },
  { immediate: true },
)
// The answer applies to the choice it was given for.
watch([workflowId, environment], () => {
  failure.value = ''
  duplicate.value = null
})
</script>

<template>
  <UDialog v-model:open="open" title="Run now" persistent>
    <LoadState
      :loading="open && workflows.isPending.value"
      :error="workflows.error.value"
      :empty="workflows.isSuccess.value && workflowOptions.length === 0"
      empty-title="No workflows yet"
      empty-description="Create a workflow in the Studio, then run it from here."
      @retry="workflows.refetch()"
    >
      <form class="run-now" @submit.prevent="submit">
        <MessageBar v-if="duplicate" intent="warning">
          {{ duplicate.message }}
          <template #actions>
            <RouterLink :to="{ name: 'operations.run', params: { runId: duplicate.runId } }" @click="open = false">
              Open the active run
            </RouterLink>
          </template>
        </MessageBar>
        <MessageBar v-if="failure" intent="error">{{ failure }}</MessageBar>
        <div class="run-now__row">
          <USelect
            v-model="workflowId"
            label="Workflow"
            placeholder="Choose a workflow"
            :options="workflowOptions"
            :description="versionNote"
            :error="cannotRun || undefined"
          />
          <USelect v-model="environment" label="Environment" :options="environmentOptions" />
        </div>
        <UTextArea
          v-model="inputsText"
          label="Inputs"
          description="A JSON object. Leave it empty to run with no inputs."
          placeholder="{ &quot;period&quot;: &quot;2026-10&quot; }"
          :rows="5"
          :error="parsedInputs.error"
        />
      </form>
    </LoadState>
    <template #footer>
      <UButton @click="open = false">Cancel</UButton>
      <UButton appearance="primary" icon="play" :disabled="!canSubmit" :loading="start.isPending.value" @click="submit">
        Run now
      </UButton>
    </template>
  </UDialog>
</template>

<style scoped>
.run-now {
  display: grid;
  gap: var(--space-12);
  min-width: 0;
}
.run-now__row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  align-items: start;
  gap: var(--space-12);
}
</style>
