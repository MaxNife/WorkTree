<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { apiGet } from '@/api/client'
import EmptyState from '@/components/EmptyState.vue'
import PageHeader from '@/components/PageHeader.vue'
import PropertyList from '@/components/PropertyList.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const health = useQuery({ queryKey: ['health'], queryFn: () => apiGet('/health'), refetchInterval: 15_000 })
const connection = computed(() => {
  if (health.isSuccess.value) return { status: 'done', label: 'Connected' }
  return health.isPending.value ? { status: 'pending', label: 'Checking' } : { status: 'failed', label: 'Unreachable' }
})
const items = computed(() => [{ key: 'api', label: 'API', value: connection.value.label }])
</script>

<template>
  <PageHeader title="Welcome" subtitle="The operations console, studio and task inbox arrive in the next checkpoints.">
    <template #actions>
      <StatusBadge :status="connection.status" :label="connection.label" />
    </template>
  </PageHeader>
  <PropertyList :items="items" />
  <EmptyState
    title="Nothing to show yet"
    description="This is the foundation build: tokens, themes, shared components and the API client."
  />
</template>
