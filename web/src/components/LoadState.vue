<script setup lang="ts">
// The states around a query, in priority order: loading, error, empty, then the content.
import { computed } from 'vue'
import EmptyState from './EmptyState.vue'
import MessageBar from './shell/MessageBar.vue'
import UButton from './UButton.vue'

const props = defineProps<{
  loading?: boolean
  error?: unknown
  empty?: boolean
  emptyTitle?: string
  emptyDescription?: string
}>()
defineEmits<{ retry: [] }>()

const hasError = computed(() => props.error !== undefined && props.error !== null && props.error !== false)
const errorMessage = computed(() => {
  if (typeof props.error === 'string' && props.error) return props.error
  const message = (props.error as { message?: unknown } | null | undefined)?.message
  return typeof message === 'string' && message ? message : 'Something went wrong.'
})
</script>

<template>
  <p v-if="loading" class="load-state__loading" role="status">Loading...</p>
  <MessageBar v-else-if="hasError" intent="error">
    {{ errorMessage }}
    <template #actions>
      <UButton @click="$emit('retry')">Retry</UButton>
    </template>
  </MessageBar>
  <EmptyState v-else-if="empty" :title="emptyTitle ?? 'Nothing to show'" :description="emptyDescription" />
  <slot v-else />
</template>

<style scoped>
.load-state__loading {
  margin: 0;
  color: var(--uaf-text-muted);
}
</style>
