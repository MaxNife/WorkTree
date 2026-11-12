<script setup lang="ts">
// Our button: a native <button>. With an icon and no text it becomes a square icon button, which needs
// `label` for its name. While `loading` it keeps focus (aria-disabled, not disabled) and refuses clicks,
// so a keyboard user does not lose their place during the work.
// Appearances: primary (Iris) is the main action of a view; strong (Night soil) is the single strongest
// action on a coloured band; destructive (Hibiscus deep) deletes or stops something.
import { computed, useSlots } from 'vue'
import type { IconName } from '@/icons/paths'
import UIcon from './UIcon.vue'

const props = withDefaults(
  defineProps<{
    appearance?: 'primary' | 'strong' | 'destructive' | 'secondary' | 'outline' | 'subtle'
    icon?: IconName
    disabled?: boolean
    loading?: boolean
    type?: 'button' | 'submit'
    label?: string
  }>(),
  { appearance: 'secondary', type: 'button' },
)
const emit = defineEmits<{ click: [event: MouseEvent] }>()

const slots = useSlots()
const shownIcon = computed(() => (props.loading ? 'retry' : props.icon))
const iconOnly = computed(() => Boolean(shownIcon.value) && !slots.default)

function onClick(event: MouseEvent): void {
  if (props.disabled || props.loading) event.preventDefault()
  else emit('click', event)
}
</script>

<template>
  <button
    class="u-button"
    :class="[`u-button--${appearance}`, { 'u-button--icon-only': iconOnly }]"
    :type="type"
    :disabled="disabled || undefined"
    :aria-disabled="(loading && !disabled) || undefined"
    :aria-label="label"
    :aria-busy="loading || undefined"
    :title="iconOnly ? label : undefined"
    :data-appearance="appearance"
    :data-icon-only="iconOnly || undefined"
    @click="onClick"
  >
    <UIcon v-if="shownIcon" :class="{ 'u-button__spinner': loading }" :name="shownIcon" :size="iconOnly ? 18 : 16" />
    <slot />
  </button>
</template>

<style scoped>
.u-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  min-height: var(--wt-control-height);
  padding: 0 var(--space-12);
  border: var(--stroke-1) solid transparent;
  border-radius: var(--wt-radius);
  background: transparent;
  color: var(--wt-ink);
  font: inherit;
  font-size: var(--font-size-14);
  font-weight: var(--weight-semibold);
  line-height: var(--line-height-20);
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color var(--motion-instant) var(--ease-out),
    border-color var(--motion-instant) var(--ease-out),
    transform var(--motion-instant) var(--ease-out);
}
.u-button:active:not(:disabled, [aria-disabled='true']) {
  transform: translateY(1px);
}
.u-button--primary {
  background: var(--wt-accent);
  color: var(--wt-on-accent);
}
.u-button--primary:hover {
  background: var(--wt-accent-hover);
}
.u-button--primary:active {
  background: var(--wt-accent-pressed);
}
.u-button--strong {
  background: var(--wt-strong);
  color: var(--wt-on-strong);
}
.u-button--strong:hover,
.u-button--strong:active {
  background: var(--wt-strong-hover);
}
.u-button--destructive {
  background: var(--wt-destructive);
  color: var(--wt-on-destructive);
}
.u-button--destructive:hover,
.u-button--destructive:active {
  background: var(--wt-destructive-hover);
}
.u-button--secondary {
  background: var(--wt-surface);
  border-color: var(--wt-line-strong);
}
.u-button--outline {
  border-color: var(--wt-line-strong);
}
.u-button--secondary:hover,
.u-button--outline:hover,
.u-button--subtle:hover {
  background: var(--wt-surface-hover);
}
.u-button--secondary:active,
.u-button--outline:active,
.u-button--subtle:active {
  background: var(--wt-surface-pressed);
}
.u-button--subtle {
  font-weight: var(--weight-regular);
}
.u-button:disabled,
.u-button[aria-disabled='true'] {
  cursor: not-allowed;
}
.u-button[aria-busy='true'] {
  opacity: 0.8;
}
.u-button:disabled {
  background: var(--wt-surface-disabled);
  border-color: transparent;
  color: var(--wt-text-disabled);
}
/* Windows High Contrast: every button gets a visible edge, and disabled reads as GrayText. */
@media (forced-colors: active) {
  .u-button {
    border-color: ButtonText;
  }
  .u-button:disabled {
    border-color: GrayText;
    color: GrayText;
  }
}
.u-button--icon-only {
  width: var(--wt-control-height);
  padding: 0;
}
.u-button__spinner {
  animation: u-button-spin calc(2 * var(--duration-slow)) linear infinite;
}
@keyframes u-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
