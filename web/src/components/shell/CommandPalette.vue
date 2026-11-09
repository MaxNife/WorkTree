<script setup lang="ts">
// Ctrl/Cmd+K command palette: a modal dialog with an ARIA combobox and listbox. Arrow keys move,
// Enter runs, Escape closes; Tab stays inside the dialog and focus returns to where it was.
// A native <input> is used on purpose: aria-activedescendant needs the options in the same document.
import { computed, nextTick, ref, watch } from 'vue'
import UIcon from '@/components/UIcon.vue'
import type { PaletteCommand } from '@/router/types'
import { filterCommands } from './commands'

const props = defineProps<{ commands: PaletteCommand[] }>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ run: [command: PaletteCommand] }>()

const query = ref('')
const active = ref(0)
const input = ref<HTMLInputElement | null>(null)
const list = ref<HTMLElement | null>(null)
let returnFocus: HTMLElement | null = null

const results = computed(() => filterCommands(props.commands, query.value))
const optionId = (index: number) => `palette-option-${index}`
const activeId = computed(() => (results.value[active.value] ? optionId(active.value) : undefined))

watch(query, () => (active.value = 0))
watch(
  open,
  async (isOpen) => {
    if (isOpen) {
      returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
      query.value = ''
      active.value = 0
      await nextTick()
      input.value?.focus()
    } else {
      const target = returnFocus
      returnFocus = null
      if (target?.isConnected) target.focus()
    }
  },
  { immediate: true },
)

function move(step: number): void {
  const count = results.value.length
  if (count === 0) return
  active.value = (active.value + step + count) % count
  void nextTick(() => list.value?.querySelector(`#${optionId(active.value)}`)?.scrollIntoView?.({ block: 'nearest' }))
}

function choose(command: PaletteCommand | undefined): void {
  if (!command) return
  open.value = false
  emit('run', command)
}

function onKeydown(event: KeyboardEvent): void {
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      move(1)
      break
    case 'ArrowUp':
      event.preventDefault()
      move(-1)
      break
    case 'Enter':
      event.preventDefault()
      choose(results.value[active.value])
      break
    case 'Escape':
      event.preventDefault()
      open.value = false
      break
    case 'Tab':
      // The search box is the only tab stop; keep focus inside the dialog.
      event.preventDefault()
      input.value?.focus()
      break
  }
}
</script>

<template>
  <div v-if="open" class="palette-backdrop" @mousedown.self="open = false">
    <div class="palette" role="dialog" aria-modal="true" aria-label="Command palette" @keydown="onKeydown">
      <div class="palette__search">
        <UIcon name="search" :size="20" class="palette__search-icon" />
        <input
          ref="input"
          v-model="query"
          class="palette__input"
          type="text"
          role="combobox"
          aria-label="Search commands"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-autocomplete="list"
          :aria-activedescendant="activeId"
          placeholder="Type a command or a place to go"
          autocomplete="off"
          spellcheck="false"
        />
      </div>
      <ul id="palette-list" ref="list" class="palette__list" role="listbox" aria-label="Commands">
        <li
          v-for="(command, index) in results"
          :id="optionId(index)"
          :key="command.id"
          class="palette__option"
          :class="{ 'is-active': index === active }"
          role="option"
          :aria-selected="index === active"
          @mousemove="active = index"
          @click="choose(command)"
        >
          <UIcon v-if="command.icon" :name="command.icon" class="palette__icon" />
          <span v-else class="palette__icon" />
          <span class="palette__label">{{ command.label }}</span>
          <span class="palette__group">{{ command.group }}</span>
        </li>
      </ul>
      <p v-if="results.length === 0" class="palette__empty">No commands match "{{ query }}".</p>
      <p class="palette__count" role="status">{{ results.length }} {{ results.length === 1 ? 'command' : 'commands' }}</p>
      <p class="palette__hint" aria-hidden="true">
        <kbd>Up</kbd>/<kbd>Down</kbd> to move, <kbd>Enter</kbd> to run, <kbd>Esc</kbd> to close
      </p>
    </div>
  </div>
</template>

<style scoped>
.palette-backdrop {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 12vh var(--space-16) 0;
  background: var(--uaf-overlay);
}
.palette {
  display: flex;
  flex-direction: column;
  width: min(640px, 100%);
  max-height: 70vh;
  border: var(--stroke-1) solid var(--uaf-border-strong);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface-raised);
  color: var(--uaf-text);
}
.palette__search {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: 0 var(--space-12);
  border-bottom: var(--stroke-1) solid var(--uaf-border);
}
.palette__search-icon {
  color: var(--uaf-text-muted);
}
.palette__input {
  flex: 1;
  min-width: 0;
  height: 44px;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  font-size: var(--font-size-16);
}
.palette__input:focus-visible {
  outline: none;
}
.palette__search:focus-within {
  box-shadow: inset 0 calc(-1 * var(--stroke-2)) 0 var(--uaf-focus);
}
.palette__list {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: var(--space-4);
  overflow-y: auto;
  list-style: none;
}
.palette__option {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-height: var(--uaf-row-height);
  padding: 0 var(--space-8);
  border-radius: var(--uaf-radius);
  cursor: pointer;
}
.palette__option.is-active {
  background: var(--uaf-surface-selected);
  box-shadow: inset var(--stroke-2) 0 0 var(--uaf-focus);
}
.palette__icon {
  flex: none;
  width: 16px;
  color: var(--uaf-text-muted);
}
.palette__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.palette__group {
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
}
.palette__empty {
  margin: 0;
  padding: var(--space-12) var(--space-12);
  color: var(--uaf-text-muted);
}
.palette__count {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.palette__hint {
  margin: 0;
  padding: var(--space-4) var(--space-12);
  border-top: var(--stroke-1) solid var(--uaf-border);
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
}
kbd {
  font-family: var(--uaf-font);
  font-weight: var(--weight-semibold);
}
</style>
