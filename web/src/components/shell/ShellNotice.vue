<script setup lang="ts">
// Plain notice pages inside the shell: page not found, no access.
import EmptyState from '@/components/EmptyState.vue'
import AppPage from './AppPage.vue'

defineProps<{ title: string; description: string }>()
</script>

<template>
  <AppPage :title="title">
    <EmptyState title="Use the sidebar or press Ctrl+K" :description="description">
      <RouterLink to="/">Go to the start page</RouterLink>
    </EmptyState>
  </AppPage>
</template>
