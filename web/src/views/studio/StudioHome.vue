<script setup lang="ts">
// Placeholder for the Studio area; replaced in CP-31.
import EmptyState from '@/components/EmptyState.vue'
import AppPage from '@/components/shell/AppPage.vue'
</script>

<template>
  <AppPage title="Studio" subtitle="Design, version and promote workflows.">
    <EmptyState title="Nothing here yet" description="Pick a workflow in the sidebar; the canvas and YAML editor arrive with the Studio." />
  </AppPage>
</template>
