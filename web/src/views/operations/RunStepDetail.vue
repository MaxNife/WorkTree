<script setup lang="ts">
// The body of one step in the run timeline: what it was, its retries and incidents, and its log.
import { computed } from 'vue'
import CodeBlock from '@/components/CodeBlock.vue'
import { stepLog, titleCase, type RunIncident, type RunStep } from './model'

const props = defineProps<{ step: RunStep; name: string; incidents: RunIncident[] }>()

const retries = computed(() => Math.max(props.step.attempts.length, props.step.attempt) - 1)
const stepIncidents = computed(() => props.incidents.filter((incident) => incident.stepId === props.step.stepId))
const log = computed(() => stepLog(props.step))
</script>

<template>
  <p class="facts">
    <span>{{ step.activity }}</span>
    <span v-if="step.outcome">Outcome: {{ step.outcome }}</span>
    <span v-if="retries > 0">{{ retries === 1 ? 'Retried once' : `Retried ${retries} times` }}</span>
    <RouterLink v-if="step.childRunId" :to="{ name: 'operations.run', params: { runId: step.childRunId } }">
      Open the child run
    </RouterLink>
  </p>
  <ul v-if="stepIncidents.length" class="incidents" aria-label="Incidents">
    <li v-for="incident in stepIncidents" :key="incident.id">
      <strong>{{ titleCase(incident.kind) }}</strong>
      {{ incident.message }}
      <span class="facts">{{ incident.resolved ? 'Resolved' : 'Open' }}</span>
    </li>
  </ul>
  <CodeBlock v-if="log" :text="log" :label="`Log for ${name}`" wrap />
</template>

<style scoped>
.facts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-12);
  margin: 0;
  color: var(--wt-muted);
  font-size: var(--font-size-12);
}
.incidents {
  display: grid;
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}
span.facts {
  display: inline;
}
</style>
