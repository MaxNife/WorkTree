<script setup lang="ts">
// A modal on the native <dialog>. showModal() traps focus and moves it inside on open; a child with
// `autofocus` takes it instead. Focus goes back to where it was on close. Every close goes through
// the model, so there is one close path.
import { onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import UButton from './UButton.vue'

const open = defineModel<boolean>('open', { default: false })
const props = withDefaults(
  defineProps<{
    title: string
    size?: 'small' | 'medium' | 'large'
    /** A backdrop click does not close it, for a dialog holding a form. Escape and Close still do. */
    persistent?: boolean
  }>(),
  { size: 'medium' },
)

const titleId = useId()
const dialog = ref<HTMLDialogElement>()
let shown = false
let returnFocus: HTMLElement | null = null

function restoreFocus(): void {
  returnFocus?.focus()
  returnFocus = null
}

function showDialog(): void {
  const element = dialog.value
  if (!element) return
  shown = true
  returnFocus = document.activeElement as HTMLElement | null
  if (typeof element.showModal === 'function') element.showModal()
  else element.setAttribute('open', '')
}

function hideDialog(): void {
  shown = false
  const element = dialog.value
  if (element && typeof element.close === 'function') element.close()
  else element?.removeAttribute('open')
  restoreFocus()
}

function sync(): void {
  if (open.value && !shown) showDialog()
  else if (!open.value && shown) hideDialog()
}

// Escape: the browser fires `cancel`. A child that handled Escape first (an open list) prevents it.
function onCancel(event: Event): void {
  event.preventDefault()
  open.value = false
}

function onEscape(event: KeyboardEvent): void {
  if (!event.defaultPrevented) open.value = false
}

// A click on the backdrop lands on the <dialog> itself; clicks on its content land on a child.
function onClick(event: MouseEvent): void {
  if (!props.persistent && event.target === dialog.value) open.value = false
}

watch(open, sync, { flush: 'post' })
onMounted(sync)
onBeforeUnmount(() => {
  if (shown) restoreFocus()
})
</script>

<template>
  <dialog
    ref="dialog"
    class="u-dialog"
    :class="`u-dialog--${size}`"
    :aria-labelledby="titleId"
    @cancel="onCancel"
    @click="onClick"
    @keydown.esc="onEscape"
  >
    <div class="u-dialog__body">
      <header class="u-dialog__header">
        <h2 :id="titleId" class="u-dialog__title">{{ title }}</h2>
        <UButton appearance="subtle" icon="close" label="Close dialog" @click="open = false" />
      </header>
      <div class="u-dialog__content"><slot /></div>
      <footer v-if="$slots.footer" class="u-dialog__footer"><slot name="footer" /></footer>
    </div>
  </dialog>
</template>

<style scoped>
.u-dialog {
  width: calc(100% - 2 * var(--space-24));
  max-height: calc(100% - 2 * var(--space-24));
  padding: 0;
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius-frame);
  background: var(--wt-surface);
  color: var(--wt-ink);
  box-shadow: var(--wt-shadow-overlay);
}
.u-dialog::backdrop {
  background: var(--wt-overlay);
}
.u-dialog--small {
  max-width: 420px;
}
.u-dialog--medium {
  max-width: 640px;
}
.u-dialog--large {
  max-width: 960px;
}
.u-dialog__body {
  display: grid;
  gap: var(--space-16);
  padding: var(--space-20) var(--space-24) var(--space-24);
}
.u-dialog__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-12);
}
.u-dialog__title {
  font-size: var(--font-size-20);
  line-height: var(--line-height-28);
  overflow-wrap: anywhere;
}
.u-dialog__content {
  min-width: 0;
}
.u-dialog__footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-8);
}
</style>
