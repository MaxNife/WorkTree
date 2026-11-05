<script setup lang="ts">
// The signed-in frame: sidebar, top bar (breadcrumbs, search, user menu), page content and the
// Ctrl/Cmd+K command palette. The login page renders outside this shell.
import { useQueryClient } from '@tanstack/vue-query'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import UIcon from '@/components/UIcon.vue'
import { AREAS } from '@/router/areas'
import { allowed, type CommandContext, type PaletteCommand } from '@/router/types'
import { useSession } from '@/stores/session'
import { useToast } from '@/stores/toast'
import AppBreadcrumbs from './AppBreadcrumbs.vue'
import AppSidebar from './AppSidebar.vue'
import CommandPalette from './CommandPalette.vue'
import { globalCommands, navigationCommands, signOut } from './commands'
import UserMenu from './UserMenu.vue'

const router = useRouter()
const session = useSession()
const context: CommandContext = { router, queryClient: useQueryClient(), toast: useToast() }

const paletteOpen = ref(false)
const main = ref<HTMLElement | null>(null)
const isMac = typeof navigator !== 'undefined' && /mac|iphone|ipad/i.test(navigator.userAgent)
const shortcut = isMac ? 'Cmd K' : 'Ctrl K'

const commands = computed<PaletteCommand[]>(() =>
  [
    ...navigationCommands(AREAS.flatMap((area) => area.navItems)),
    ...AREAS.flatMap((area) => area.commands),
    ...globalCommands(),
  ].filter((command) => allowed(command.roles, session.roles)),
)

function onKeydown(event: KeyboardEvent): void {
  if (event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
    event.preventDefault()
    paletteOpen.value = !paletteOpen.value
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

function focusMain(): void {
  main.value?.focus()
}

async function run(command: PaletteCommand): Promise<void> {
  try {
    await command.run(context)
  } catch (error) {
    context.toast.error(error instanceof Error ? error.message : `Could not run "${command.label}".`)
  }
  // If the command replaced the page, the control that had focus is gone: continue from the content.
  await nextTick()
  if (main.value?.isConnected && (!document.activeElement || document.activeElement === document.body)) focusMain()
}
</script>

<template>
  <div class="shell">
    <a class="shell__skip" href="#main" @click.prevent="focusMain">Skip to main content</a>
    <div class="shell__frame" :inert="paletteOpen || undefined">
      <AppSidebar />
      <div class="shell__column">
        <header class="shell__top">
          <AppBreadcrumbs />
          <div class="shell__tools">
            <button
              type="button"
              class="shell__search"
              aria-haspopup="dialog"
              :aria-keyshortcuts="isMac ? 'Meta+K' : 'Control+K'"
              @click="paletteOpen = true"
            >
              <UIcon name="search" />
              <span class="shell__search-text">Search or run a command</span>
              <kbd class="shell__kbd">{{ shortcut }}</kbd>
            </button>
            <UserMenu @sign-out="signOut(context)" />
          </div>
        </header>
        <main id="main" ref="main" class="shell__main" tabindex="-1">
          <RouterView />
        </main>
      </div>
    </div>
    <CommandPalette v-model:open="paletteOpen" :commands="commands" @run="run" />
  </div>
</template>

<style scoped>
.shell {
  height: 100%;
}
.shell__skip {
  position: absolute;
  top: var(--spacingVerticalS);
  left: var(--spacingHorizontalS);
  z-index: 50;
  padding: var(--spacingVerticalXS) var(--spacingHorizontalS);
  border-radius: var(--uaf-radius);
  background: var(--uaf-accent);
  color: var(--uaf-on-accent);
  transform: translateY(-200%);
}
.shell__skip:focus {
  transform: none;
}
.shell__frame {
  display: flex;
  height: 100%;
  min-width: 0;
}
.shell__column {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}
.shell__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacingHorizontalL);
  min-height: 44px;
  padding: var(--spacingVerticalXS) var(--uaf-page-padding);
  border-bottom: var(--strokeWidthThin) solid var(--uaf-border);
}
.shell__tools {
  display: flex;
  flex: none;
  align-items: center;
  gap: var(--spacingHorizontalS);
}
.shell__search {
  display: inline-flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  height: var(--uaf-control-height);
  padding: 0 var(--spacingHorizontalS);
  border: var(--strokeWidthThin) solid var(--uaf-border);
  border-radius: var(--uaf-radius);
  background: var(--uaf-surface);
  color: var(--uaf-text-muted);
  font: inherit;
  cursor: pointer;
}
.shell__search:hover {
  border-color: var(--uaf-border-strong);
  color: var(--uaf-text);
}
.shell__kbd {
  font-family: var(--uaf-font);
  font-size: var(--fontSizeBase200);
}
.shell__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: var(--uaf-page-padding);
}
.shell__main:focus {
  outline: none;
}
@media (max-width: 1100px) {
  .shell__search-text {
    display: none;
  }
}
</style>
