<script setup lang="ts">
// Thin wrapper over <fluent-button>: screens never use Fluent elements directly. With an icon and no
// text it becomes a square icon button, which needs `label` for its name. While `loading` it keeps
// focus and refuses clicks, so a keyboard user does not lose their place during the work.
import { computed, useSlots } from 'vue'
import type { IconName } from '@/icons/paths'
import UIcon from './UIcon.vue'

const props = withDefaults(
  defineProps<{
    appearance?: 'primary' | 'secondary' | 'outline' | 'subtle'
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

// Our listener runs before Fluent's, so Fluent's own block on a disabled-focusable click is too late.
function onClick(event: MouseEvent): void {
  if (props.disabled || props.loading) event.preventDefault()
  else emit('click', event)
}
</script>

<template>
  <fluent-button
    class="u-button"
    :appearance="appearance"
    :disabled="disabled || undefined"
    :disabled-focusable="(loading && !disabled) || undefined"
    :icon-only="iconOnly || undefined"
    :type="type"
    :aria-label="label"
    :aria-busy="loading || undefined"
    :title="iconOnly ? label : undefined"
    size="small"
    @click="onClick"
  >
    <!-- eslint-disable-next-line vue/no-deprecated-slot-attribute -- native custom-element slot -->
    <UIcon v-if="shownIcon" :slot="iconOnly ? undefined : 'start'" :class="{ 'u-button__spinner': loading }" :name="shownIcon" />
    <slot />
  </fluent-button>
</template>

<style scoped>
.u-button {
  min-height: var(--uaf-control-height);
  padding-inline: var(--spacingHorizontalM);
  font-size: var(--fontSizeBase300);
  line-height: var(--lineHeightBase300);
}
.u-button[icon-only] {
  min-width: var(--uaf-control-height);
  max-width: var(--uaf-control-height);
  padding: 0;
}
.u-button__spinner {
  animation: u-button-spin calc(2 * var(--durationUltraSlow)) linear infinite;
}
@keyframes u-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
