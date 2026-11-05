<script setup lang="ts">
// A modal over <fluent-dialog>. The browser's <dialog> traps focus and moves it inside on open; a
// child with `autofocus` takes it instead. Focus goes back to where it was on close.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UButton from './UButton.vue'

const open = defineModel<boolean>('open', { default: false })
withDefaults(defineProps<{ title: string; size?: 'small' | 'medium' | 'large' }>(), { size: 'medium' })

const dialog = ref<HTMLElement & { show?: () => void; hide?: () => void }>()
let shown = false
let returnFocus: HTMLElement | null = null

function restoreFocus(): void {
  returnFocus?.focus()
  returnFocus = null
}

function showDialog(): void {
  shown = true
  returnFocus = document.activeElement as HTMLElement | null
  dialog.value?.show?.()
}

function hideDialog(): void {
  shown = false
  dialog.value?.hide?.()
  restoreFocus()
}

function sync(): void {
  if (open.value && !shown) showDialog()
  else if (!open.value && shown) hideDialog()
}

// Fluent closed itself: the Escape key (`cancel`) or a click on the backdrop.
function onToggle(event: Event): void {
  if ((event as CustomEvent<{ newState?: string }>).detail?.newState !== 'closed' || !shown) return
  shown = false
  open.value = false
  restoreFocus()
}

function onEscape(event: KeyboardEvent): void {
  if (!event.defaultPrevented) open.value = false
}

// Skip Fluent's own close handler so there is one close path, through the model.
function onClose(event: MouseEvent): void {
  event.preventDefault()
  open.value = false
}

watch(open, sync, { flush: 'post' })
onMounted(sync)
onBeforeUnmount(() => {
  if (shown) restoreFocus()
})
</script>

<template>
  <fluent-dialog
    ref="dialog"
    class="u-dialog"
    :class="`u-dialog--${size}`"
    :aria-label="title"
    @toggle.self="onToggle"
    @keydown.esc="onEscape"
  >
    <fluent-dialog-body>
      <!-- eslint-disable vue/no-deprecated-slot-attribute -- native custom-element slots -->
      <h2 slot="title" class="u-dialog__title">{{ title }}</h2>
      <UButton slot="close" appearance="subtle" icon="close" label="Close dialog" @click="onClose" />
      <slot />
      <div v-if="$slots.footer" slot="action" class="u-dialog__footer"><slot name="footer" /></div>
      <!-- eslint-enable vue/no-deprecated-slot-attribute -->
    </fluent-dialog-body>
  </fluent-dialog>
</template>

<style scoped>
.u-dialog::part(dialog) {
  border: var(--strokeWidthThin) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
  box-shadow: none;
}
.u-dialog--small::part(dialog) {
  max-width: 420px;
}
.u-dialog--medium::part(dialog) {
  max-width: 640px;
}
.u-dialog--large::part(dialog) {
  max-width: 960px;
}
.u-dialog__title {
  font-size: var(--fontSizeBase400);
}
.u-dialog__footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--spacingHorizontalS);
}
</style>
