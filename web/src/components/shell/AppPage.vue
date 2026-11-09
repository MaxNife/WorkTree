<script setup lang="ts">
// The frame of every screen: the page header, an optional command bar and the content. Breadcrumbs
// are drawn by the shell from route meta, so pages do not repeat them.
//   #actions   primary actions on the right of the title
//   #commands  the page command bar (Azure style) under the title: UButtons, filters, view switches
//   #messages  MessageBars shown above the content
import PageHeader from '@/components/PageHeader.vue'

defineProps<{ title: string; subtitle?: string; commandsLabel?: string }>()
</script>

<template>
  <div class="app-page">
    <PageHeader :title="title" :subtitle="subtitle">
      <template v-if="$slots.actions" #actions><slot name="actions" /></template>
    </PageHeader>
    <div v-if="$slots.commands" class="app-page__commands" role="group" :aria-label="commandsLabel ?? 'Page commands'">
      <slot name="commands" />
    </div>
    <div v-if="$slots.messages" class="app-page__messages"><slot name="messages" /></div>
    <div class="app-page__body"><slot /></div>
  </div>
</template>

<style scoped>
.app-page {
  display: grid;
  gap: var(--uaf-gap);
  min-width: 0;
}
.app-page__commands {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
  padding-bottom: var(--uaf-gap);
  border-bottom: var(--stroke-1) solid var(--uaf-border);
}
.app-page__messages {
  display: grid;
  gap: var(--space-8);
}
.app-page__body {
  min-width: 0;
}
</style>
