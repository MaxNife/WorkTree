<script setup lang="ts">
// The frame of every screen: the page header, an optional command bar and the content. Breadcrumbs
// are drawn by the shell from route meta, so pages do not repeat them.
// With `band` (an area colour) or `workflowId`, the header is the area band (docs/04 5) instead of
// the plain header; the title, subtitle and actions move into it, so the page still has one h1.
//   #actions   primary actions on the right of the title (on a band: one `strong` button at most)
//   #badges    pills beside the title (band only), for example a run's status
//   #commands  the page command bar under the title: UButtons, filters, view switches
//   #messages  MessageBars shown above the content
import AreaBand from '@/components/AreaBand.vue'
import PageHeader from '@/components/PageHeader.vue'
import type { AreaColour } from '@/theme/areas'

defineProps<{
  title: string
  subtitle?: string
  commandsLabel?: string
  band?: AreaColour
  bandSize?: 'tall' | 'short'
  workflowId?: string
  environment?: string
}>()
</script>

<template>
  <div class="app-page">
    <AreaBand
      v-if="band || workflowId"
      :colour="band"
      :workflow-id="workflowId"
      :title="title"
      :summary="subtitle"
      :size="bandSize"
      :environment="environment"
    >
      <template v-if="$slots.badges" #badges><slot name="badges" /></template>
      <template v-if="$slots.actions" #action><slot name="actions" /></template>
    </AreaBand>
    <PageHeader v-else :title="title" :subtitle="subtitle">
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
  gap: var(--wt-gap);
  min-width: 0;
}
.app-page__commands {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
  padding-bottom: var(--wt-gap);
  border-bottom: var(--stroke-1) solid var(--wt-line);
}
.app-page__messages {
  display: grid;
  gap: var(--space-8);
}
.app-page__body {
  min-width: 0;
}
</style>
