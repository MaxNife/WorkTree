<script setup lang="ts">
// Toasts from useToast(). The two live regions are always in the DOM (empty at start) so screen
// readers announce what is added: success/info politely, errors assertively.
import { computed } from 'vue'
import UIcon from '@/components/UIcon.vue'
import type { IconName } from '@/icons/paths'
import { useToastStore, type ToastIntent } from '@/stores/toast'

const store = useToastStore()
const polite = computed(() => store.toasts.filter((toast) => toast.intent !== 'error'))
const urgent = computed(() => store.toasts.filter((toast) => toast.intent === 'error'))
const ICONS: Record<ToastIntent, IconName> = { success: 'check-circle', info: 'info', error: 'error' }
const regions = computed(() => [
  { key: 'polite', role: 'status', live: 'polite' as const, toasts: polite.value },
  { key: 'urgent', role: 'alert', live: 'assertive' as const, toasts: urgent.value },
])
</script>

<template>
  <div class="toasts">
    <div v-for="region in regions" :key="region.key" class="toasts__region" :role="region.role" :aria-live="region.live">
      <div
        v-for="toast in region.toasts"
        :key="toast.id"
        class="toast"
        :class="`toast--${toast.intent}`"
        @mouseenter="store.pause(toast.id)"
        @mouseleave="store.resume(toast.id)"
        @focusin="store.pause(toast.id)"
        @focusout="store.resume(toast.id)"
      >
        <UIcon :name="ICONS[toast.intent]" :size="16" class="toast__icon" />
        <span class="toast__message">{{ toast.message }}</span>
        <button type="button" class="toast__dismiss" aria-label="Dismiss notification" @click="store.dismiss(toast.id)">
          <UIcon name="close" :size="16" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  right: var(--space-16);
  bottom: var(--space-16);
  z-index: 40;
  display: grid;
  gap: var(--space-8);
  width: min(360px, calc(100vw - 2 * var(--space-16)));
  pointer-events: none;
}
.toasts__region {
  display: grid;
  gap: var(--space-8);
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: var(--space-8);
  padding: var(--space-8) var(--space-12);
  border: var(--stroke-1) solid var(--uaf-border-strong);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface-raised);
  pointer-events: auto;
}
.toast__icon {
  margin-top: 2px;
  color: var(--uaf-text-muted);
}
.toast--success .toast__icon {
  color: var(--uaf-ok);
}
.toast--error {
  border-color: var(--uaf-danger-border);
}
.toast--error .toast__icon {
  color: var(--uaf-danger);
}
.toast__message {
  flex: 1;
  min-width: 0;
}
.toast__dismiss {
  display: inline-flex;
  padding: 2px;
  border: 0;
  border-radius: var(--uaf-radius);
  background: none;
  color: var(--uaf-text-muted);
  cursor: pointer;
}
.toast__dismiss:hover {
  color: var(--uaf-text);
}
</style>
