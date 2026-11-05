<script setup lang="ts">
// The user menu: theme and density switchers and sign-out (ARIA menu button pattern). Arrow keys,
// Home and End move between items; Escape closes and returns focus to the button; Tab closes.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import UIcon from '@/components/UIcon.vue'
import { usePreferences } from '@/stores/preferences'
import { useSession } from '@/stores/session'
import type { Density, ThemeMode } from '@/theme/apply'
import { THEME_LABELS } from '@/theme/tokens'

const emit = defineEmits<{ signOut: [] }>()

const session = useSession()
const preferences = usePreferences()
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)

const name = computed(() => session.user?.displayName ?? 'Account')
const roleText = computed(() => session.roles.join(', ') || 'no roles')
const modes: { value: ThemeMode; label: string }[] = [
  { value: 'system', label: 'Follow the system' },
  { value: 'light', label: THEME_LABELS.light },
  { value: 'dark', label: THEME_LABELS.dark },
  { value: 'high-contrast', label: THEME_LABELS['high-contrast'] },
]
const densities: { value: Density; label: string }[] = [
  { value: 'compact', label: 'Compact' },
  { value: 'comfortable', label: 'Comfortable' },
]

function items(): HTMLElement[] {
  return [...(menu.value?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])]
}

function focusItem(index: number): void {
  const all = items()
  if (all.length === 0) return
  all[(index + all.length) % all.length]?.focus()
}

async function show(index = 0): Promise<void> {
  open.value = true
  await nextTick()
  focusItem(index)
}

function close(restoreFocus = true): void {
  open.value = false
  if (restoreFocus) trigger.value?.focus()
}

function onMenuKeydown(event: KeyboardEvent): void {
  const all = items()
  const current = all.indexOf(document.activeElement as HTMLElement)
  const keys: Record<string, () => void> = {
    ArrowDown: () => focusItem(current + 1),
    ArrowUp: () => focusItem(current - 1),
    Home: () => focusItem(0),
    End: () => focusItem(all.length - 1),
    Escape: () => close(),
  }
  const action = keys[event.key]
  if (action) {
    event.preventDefault()
    action()
  } else if (event.key === 'Tab') {
    close(false)
  }
}

function onOutside(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) close(false)
}

watch(open, (isOpen) => {
  if (isOpen) document.addEventListener('pointerdown', onOutside)
  else document.removeEventListener('pointerdown', onOutside)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutside))

function signOut(): void {
  close(false)
  emit('signOut')
}
</script>

<template>
  <div ref="root" class="user-menu">
    <button
      ref="trigger"
      type="button"
      class="user-menu__trigger"
      aria-haspopup="menu"
      :aria-expanded="open"
      aria-controls="user-menu"
      :title="`Signed in as ${session.user?.username ?? ''} (${roleText})`"
      @click="open ? close(false) : show()"
      @keydown.down.prevent="show(0)"
      @keydown.up.prevent="show(-1)"
    >
      <UIcon name="person" :size="20" />
      <span class="user-menu__name">{{ name }}</span>
      <UIcon name="chevron-down" :size="12" />
    </button>
    <div v-if="open" id="user-menu" ref="menu" class="user-menu__panel" role="menu" :aria-label="`${name} menu`" @keydown="onMenuKeydown">
      <div role="group" aria-labelledby="user-menu-theme">
        <p id="user-menu-theme" class="user-menu__heading" role="presentation">Theme</p>
        <button
          v-for="mode in modes"
          :key="mode.value"
          type="button"
          class="user-menu__item"
          role="menuitemradio"
          tabindex="-1"
          :aria-checked="preferences.mode === mode.value"
          @click="preferences.setMode(mode.value)"
        >
          <UIcon v-if="preferences.mode === mode.value" name="check" class="user-menu__mark" />
          <span v-else class="user-menu__mark" />
          {{ mode.label }}
        </button>
      </div>
      <div role="separator" class="user-menu__separator" />
      <div role="group" aria-labelledby="user-menu-density">
        <p id="user-menu-density" class="user-menu__heading" role="presentation">Density</p>
        <button
          v-for="density in densities"
          :key="density.value"
          type="button"
          class="user-menu__item"
          role="menuitemradio"
          tabindex="-1"
          :aria-checked="preferences.density === density.value"
          @click="preferences.setDensity(density.value)"
        >
          <UIcon v-if="preferences.density === density.value" name="check" class="user-menu__mark" />
          <span v-else class="user-menu__mark" />
          {{ density.label }}
        </button>
      </div>
      <div role="separator" class="user-menu__separator" />
      <button type="button" class="user-menu__item" role="menuitem" tabindex="-1" @click="signOut">
        <UIcon name="sign-out" class="user-menu__mark" />
        Sign out
      </button>
    </div>
  </div>
</template>

<style scoped>
.user-menu {
  position: relative;
}
.user-menu__trigger {
  display: inline-flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  max-width: 220px;
  height: var(--uaf-control-height);
  padding: 0 var(--spacingHorizontalS);
  border: 0;
  border-radius: var(--uaf-radius);
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.user-menu__trigger:hover,
.user-menu__trigger[aria-expanded='true'] {
  background: var(--uaf-surface-hover);
}
.user-menu__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-menu__panel {
  position: absolute;
  top: calc(100% + var(--spacingVerticalXS));
  right: 0;
  z-index: 20;
  min-width: 220px;
  padding: var(--spacingVerticalXS);
  border: var(--strokeWidthThin) solid var(--uaf-border-strong);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface-raised);
}
.user-menu__heading {
  margin: 0;
  padding: var(--spacingVerticalXS) var(--spacingHorizontalS);
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
.user-menu__item {
  display: flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  width: 100%;
  min-height: var(--uaf-control-height);
  padding: 0 var(--spacingHorizontalS);
  border: 0;
  border-radius: var(--uaf-radius);
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.user-menu__item:hover,
.user-menu__item:focus-visible {
  background: var(--uaf-surface-hover);
}
.user-menu__mark {
  flex: none;
  width: 16px;
}
.user-menu__separator {
  margin: var(--spacingVerticalXS) 0;
  border-top: var(--strokeWidthThin) solid var(--uaf-border);
}
</style>
