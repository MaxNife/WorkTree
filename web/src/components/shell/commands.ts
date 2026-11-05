// Palette commands that belong to the shell, plus the filter used by the command palette.
import type { NavItem, PaletteCommand, CommandContext, Role } from '@/router/types'
import { usePreferences } from '@/stores/preferences'
import { useSession } from '@/stores/session'
import { THEME_LABELS } from '@/theme/tokens'
import { useShellLayout } from './layout'

/** "Go to ..." for every sidebar link (static entries only); child entries inherit role limits. */
export function navigationCommands(items: NavItem[], inherited: Role[] = []): PaletteCommand[] {
  return items.flatMap((item) => {
    const roles = [...inherited, ...(item.roles ?? [])]
    const own: PaletteCommand[] = item.to
      ? [
          {
            id: `go.${item.id}`,
            label: `Go to ${item.label}`,
            group: 'Navigation',
            icon: item.icon,
            roles: roles.length ? roles : undefined,
            run: ({ router }) => router.push(item.to as string).then(() => undefined),
          },
        ]
      : []
    return [...own, ...navigationCommands(item.children ?? [], roles)]
  })
}

/** Sign out on the server, drop cached data so the next user sees none of it, and go to the login page. */
export async function signOut({ router, queryClient, toast }: CommandContext): Promise<void> {
  try {
    await useSession().logout()
  } catch {
    toast.error('The server did not confirm the sign-out. You are signed out on this device.')
  }
  queryClient.clear()
  await router.push({ name: 'login' })
}

export function globalCommands(): PaletteCommand[] {
  const themes = (['system', 'light', 'dark', 'high-contrast'] as const).map(
    (mode): PaletteCommand => ({
      id: `theme.${mode}`,
      label: `Theme: ${mode === 'system' ? 'Follow the system' : THEME_LABELS[mode]}`,
      group: 'Preferences',
      icon: mode === 'dark' ? 'moon' : mode === 'high-contrast' ? 'contrast' : 'sun',
      keywords: ['appearance', 'colour', 'color'],
      run: () => usePreferences().setMode(mode),
    }),
  )
  const densities = (['compact', 'comfortable'] as const).map(
    (density): PaletteCommand => ({
      id: `density.${density}`,
      label: `Density: ${density === 'compact' ? 'Compact' : 'Comfortable'}`,
      group: 'Preferences',
      icon: 'view-table',
      keywords: ['spacing', 'rows'],
      run: () => usePreferences().setDensity(density),
    }),
  )
  return [
    ...themes,
    ...densities,
    {
      id: 'shell.toggle-sidebar',
      label: 'Collapse or expand the sidebar',
      group: 'Layout',
      icon: 'panel-collapse',
      keywords: ['navigation', 'menu'],
      run: () => useShellLayout().toggleCollapsed(),
    },
    {
      id: 'shell.design',
      label: 'Open the design language reference',
      group: 'Help',
      icon: 'info',
      keywords: ['tokens', 'components'],
      run: ({ router }) => router.push('/design').then(() => undefined),
    },
    { id: 'session.sign-out', label: 'Sign out', group: 'Account', icon: 'sign-out', keywords: ['log out'], run: signOut },
  ]
}

/** Every search word must appear in the label, group or keywords; label matches rank first. */
export function filterCommands(commands: PaletteCommand[], query: string): PaletteCommand[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const first = words[0]
  if (!first) return commands
  const ranked: { command: PaletteCommand; rank: number; index: number }[] = []
  commands.forEach((command, index) => {
    const label = command.label.toLowerCase()
    const text = [label, command.group.toLowerCase(), ...(command.keywords ?? []).map((k) => k.toLowerCase())].join(' ')
    if (!words.every((word) => text.includes(word))) return
    const rank = label.split(/\s+/).some((part) => part.startsWith(first)) ? 0 : label.includes(first) ? 1 : 2
    ranked.push({ command, rank, index })
  })
  return ranked.sort((a, b) => a.rank - b.rank || a.index - b.index).map((entry) => entry.command)
}
