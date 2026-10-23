<script setup lang="ts">
// Thin wrapper over <fluent-button>: screens never use Fluent elements directly.
import type { IconName } from '@/icons/paths'
import UIcon from './UIcon.vue'

withDefaults(
  defineProps<{
    appearance?: 'primary' | 'secondary' | 'outline' | 'subtle'
    icon?: IconName
    disabled?: boolean
    type?: 'button' | 'submit'
    label?: string
  }>(),
  { appearance: 'secondary', type: 'button' },
)
defineEmits<{ click: [event: MouseEvent] }>()
</script>

<template>
  <fluent-button
    :appearance="appearance"
    :disabled="disabled || undefined"
    :type="type"
    :aria-label="label"
    size="small"
    @click="$emit('click', $event)"
  >
    <!-- eslint-disable-next-line vue/no-deprecated-slot-attribute -- native custom-element slot -->
    <UIcon v-if="icon" slot="start" :name="icon" />
    <slot />
  </fluent-button>
</template>
