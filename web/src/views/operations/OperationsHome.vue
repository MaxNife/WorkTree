<script setup lang="ts">
// Placeholder for the Operations area; replaced in CP-29.
import EmptyState from '@/components/EmptyState.vue'
import AppPage from '@/components/shell/AppPage.vue'
</script>

<template>
  <AppPage title="Operations" subtitle="Runs, schedules and incidents across all workflows.">
    <EmptyState title="Nothing here yet" description="The dashboard, run history and run detail arrive with the Operations console." />
  </AppPage>
</template>
