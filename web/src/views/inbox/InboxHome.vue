<script setup lang="ts">
// Placeholder for the Inbox area; replaced in CP-30.
import EmptyState from '@/components/EmptyState.vue'
import AppPage from '@/components/shell/AppPage.vue'
</script>

<template>
  <AppPage title="Inbox" subtitle="Human tasks waiting for you or your role.">
    <EmptyState title="Nothing here yet" description="Claim and complete tasks here once the Task Inbox lands." />
  </AppPage>
</template>
