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
  border: var(--stroke-1) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface-sunken);
}
.message-bar__icon {
  margin-top: 2px;
  color: var(--uaf-text-secondary);
}
.message-bar--success {
  border-color: var(--uaf-ok-border);
  background: var(--uaf-ok-bg);
}
.message-bar--success .message-bar__icon {
  color: var(--uaf-ok);
}
.message-bar--warning {
  border-color: var(--uaf-warn-border);
  background: var(--uaf-warn-bg);
}
.message-bar--warning .message-bar__icon {
  color: var(--uaf-warn);
}
.message-bar--error {
  border-color: var(--uaf-danger-border);
  background: var(--uaf-danger-bg);
}
.message-bar--error .message-bar__icon {
  color: var(--uaf-danger);
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
  border-radius: var(--uaf-radius);
  background: none;
  color: var(--uaf-text-muted);
  cursor: pointer;
}
.message-bar__dismiss:hover {
  color: var(--uaf-text);
}
</style>
