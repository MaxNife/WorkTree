<script setup lang="ts">
// An inline message for a page or form: icon, optional title, text and actions.
// Errors and warnings use role="alert" so they are announced when they appear; others use "status".
import { computed } from 'vue'
import UIcon from '@/components/UIcon.vue'
import type { IconName } from '@/icons/paths'

export type MessageIntent = 'info' | 'success' | 'warning' | 'error'

const props = defineProps<{ intent?: MessageIntent; title?: string; dismissible?: boolean }>()
defineEmits<{ dismiss: [] }>()

const intent = computed<MessageIntent>(() => props.intent ?? 'info')
const ICONS: Record<MessageIntent, IconName> = { info: 'info', success: 'check-circle', warning: 'warning', error: 'error' }
</script>

<template>
  <div class="message-bar" :class="`message-bar--${intent}`" :role="intent === 'error' || intent === 'warning' ? 'alert' : 'status'">
    <UIcon :name="ICONS[intent]" :size="18" weight="fill" class="message-bar__icon" />
    <div class="message-bar__text">
      <strong v-if="title" class="message-bar__title">{{ title }}</strong>
      <slot />
    </div>
    <div v-if="$slots.actions" class="message-bar__actions"><slot name="actions" /></div>
    <button v-if="dismissible" type="button" class="message-bar__dismiss" aria-label="Dismiss message" @click="$emit('dismiss')">
      <UIcon name="close" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.message-bar {
  display: flex;
  align-items: flex-start;
  gap: var(--space-10);
  padding: var(--space-10) var(--space-12);
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius-container);
  background: var(--wt-sunken);
}
.message-bar__icon {
  margin-top: 2px;
  color: var(--wt-text-secondary);
}
.message-bar--success {
  border-color: var(--wt-ok-border);
  background: var(--wt-ok-bg);
}
.message-bar--success .message-bar__icon {
  color: var(--wt-ok);
}
.message-bar--warning {
  border-color: var(--wt-warn-border);
  background: var(--wt-warn-bg);
}
.message-bar--warning .message-bar__icon {
  color: var(--wt-warn);
}
.message-bar--error {
  border-color: var(--wt-danger-border);
  background: var(--wt-danger-bg);
}
.message-bar--error .message-bar__icon {
  color: var(--wt-danger);
}
.message-bar__text {
  flex: 1;
  min-width: 0;
}
.message-bar__title {
  margin-right: var(--space-6);
  font-weight: var(--weight-semibold);
}
.message-bar__text {
  line-height: var(--line-height-22);
}
.message-bar__actions {
  display: flex;
  gap: var(--space-8);
}
.message-bar__dismiss {
  display: inline-flex;
  padding: 2px;
  border: 0;
  border-radius: var(--wt-radius);
  background: none;
  color: var(--wt-muted);
  cursor: pointer;
}
.message-bar__dismiss:hover {
  color: var(--wt-ink);
}
</style>
