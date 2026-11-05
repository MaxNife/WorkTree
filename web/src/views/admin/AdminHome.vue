<script setup lang="ts">
// Placeholder for the Admin area; replaced in CP-32.
import EmptyState from '@/components/EmptyState.vue'
import AppPage from '@/components/shell/AppPage.vue'
</script>

<template>
  <AppPage title="Admin" subtitle="Users, roles, secrets metadata and the audit log.">
    <EmptyState title="Nothing here yet" description="User, role, secret and audit screens arrive with the Admin area." />
  </AppPage>
</template>
