import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, type Router } from 'vue-router'
import { apiSend, setCsrfToken } from '@/api/client'
import App from '@/App.vue'
import { breadcrumbsFor, useCrumbLabel } from '@/components/shell/breadcrumbs'
import { filterCommands } from '@/components/shell/commands'
import MessageBar from '@/components/shell/MessageBar.vue'
import { createAppRouter } from '@/router'
import { loadWorkflowTree } from '@/router/areas/studio'
import { safeRedirect, type PaletteCommand, type Role } from '@/router/types'
import { useToast } from '@/stores/toast'

interface Server {
  roles: Role[] | null
  workflows?: { id: string; name: string; folder: string | null }[]
  login?: (body: { username: string; password: string }) => Response
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function me(roles: Role[]) {
  return { user: { id: 'u1', username: 'ada', display_name: 'Ada Lovelace', roles }, roles, permissions: [], csrf_token: 'tok-1' }
}

function stubServer(server: Server) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/auth/me') return server.roles ? json(200, me(server.roles)) : json(401, { error: { code: 'unauthorized', message: 'no' } })
    if (url === '/api/auth/login' && server.login) return server.login(JSON.parse(String(init?.body)))
    if (url === '/api/auth/logout') return json(200, { ok: true })
    if (url.startsWith('/api/workflows')) return json(200, server.workflows ?? [])
    return json(404, { error: { code: 'not_found', message: url } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

let wrapper: VueWrapper | null = null

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await flushPromises()
    await vi.dynamicImportSettled()
  }
}

async function mountApp(path: string, server: Server): Promise<{ router: Router; fetchMock: ReturnType<typeof stubServer> }> {
  const fetchMock = stubServer(server)
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory(), pinia)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  await router.push(path)
  await router.isReady()
  wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [pinia, router, [VueQueryPlugin, { queryClient }]] },
  })
  await settle()
  return { router, fetchMock }
}

function navLabels(): string[] {
  return wrapper!.findAll('#app-nav .nav-item__label').map((node) => node.text())
}

function press(target: Element, key: string, options: KeyboardEventInit = {}): void {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...options }))
}

beforeEach(() => {
  window.localStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('route guard', () => {
  it('sends anonymous users to the login page and keeps where they were going', async () => {
    const { router } = await mountApp('/inbox', { roles: null })
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/inbox')
    expect(wrapper!.find('#app-nav').exists()).toBe(false)
  })

  it('blocks role-limited pages typed into the address bar', async () => {
    const { router } = await mountApp('/admin', { roles: ['operator'] })
    expect(router.currentRoute.value.name).toBe('forbidden')
    expect(wrapper!.text()).toContain('You do not have access')
  })

  it('only follows redirects that stay on this site', () => {
    expect(safeRedirect('/studio')).toBe('/studio')
    expect(safeRedirect('//evil.example')).toBeNull()
    expect(safeRedirect('https://evil.example')).toBeNull()
    expect(safeRedirect(['/x'])).toBeNull()
  })
})

describe('sidebar', () => {
  it('renders the five areas from the area modules for an admin', async () => {
    await mountApp('/operations', { roles: ['admin'] })
    expect(navLabels()).toEqual(['Operations', 'Inbox', 'Studio', 'Data', 'Admin'])
    const current = wrapper!.find('#app-nav a[aria-current="page"]')
    expect(current.text()).toBe('Operations')
  })

  // F5: Dashboard and the Operations row share /operations, and Runs lies under it. Only one lights.
  it('marks exactly one entry current, the deepest longest match', async () => {
    const { router } = await mountApp('/operations', { roles: ['admin'] })
    await wrapper!.get('button[aria-label="Operations items"]').trigger('click')
    await settle()
    const currentLabels = () => wrapper!.findAll('#app-nav [aria-current="page"]').map((node) => node.text())
    expect(currentLabels()).toEqual(['Dashboard'])
    expect(wrapper!.find('#app-nav .nav-item__row.is-in-area').text()).toContain('Operations')
    await router.push('/operations/runs/run-1')
    await settle()
    expect(currentLabels()).toEqual(['Runs'])
    await wrapper!.get('button[aria-label="Operations items"]').trigger('click')
    await settle()
    expect(currentLabels()).toEqual(['Operations'])
  })

  it('marks each area with a leaf in its colour', async () => {
    await mountApp('/operations', { roles: ['admin'] })
    const leaves = wrapper!.findAll('#app-nav .leaf').map((node) => node.attributes('style'))
    expect(leaves).toHaveLength(5)
    expect(leaves[0]).toContain('--wt-hibiscus')
    expect(leaves[4]).toContain('--wt-ink')
  })

  it('hides Admin from other roles', async () => {
    await mountApp('/operations', { roles: ['operator', 'author'] })
    expect(navLabels()).toEqual(['Operations', 'Inbox', 'Studio', 'Data'])
  })

  it('shows Studio workflows grouped by folder when expanded', async () => {
    await mountApp('/studio', {
      roles: ['author'],
      workflows: [
        { id: 'w1', name: 'Bank reconciliation', folder: 'Finance' },
        { id: 'w2', name: 'Vendor onboarding', folder: null },
      ],
    })
    const toggle = wrapper!.get('button[aria-label="Studio items"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    await settle()
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(navLabels()).toEqual(expect.arrayContaining(['Finance', 'Unfiled']))
    await wrapper!.get('button.nav-item__link--group').trigger('click')
    await settle()
    expect(wrapper!.get('a[href="/studio/workflows/w1"]').text()).toBe('Bank reconciliation')
  })

  it('remembers that it was collapsed', async () => {
    await mountApp('/operations', { roles: ['viewer'] })
    await wrapper!.get('button[aria-label="Collapse sidebar"]').trigger('click')
    expect(wrapper!.find('.sidebar--collapsed').exists()).toBe(true)
    // Icon rail: links keep an accessible name.
    expect(wrapper!.find('#app-nav a[aria-label="Inbox"]').exists()).toBe(true)
    // Each area's glyph sits on a leaf; the current area's row is marked for its ink ring.
    expect(wrapper!.findAll('#app-nav .nav-item__rail-leaf')).toHaveLength(4)
    expect(wrapper!.get('#app-nav .nav-item__row--rail.is-in-area a').attributes('aria-label')).toBe('Operations')
    wrapper!.unmount()
    wrapper = null

    await mountApp('/operations', { roles: ['viewer'] })
    expect(wrapper!.find('.sidebar--collapsed').exists()).toBe(true)
    expect(wrapper!.get('button[aria-label="Expand sidebar"]').attributes('aria-expanded')).toBe('false')
  })
})

describe('studio workflow tree', () => {
  it('groups by folder, unfiled last, and lists flat when there are no folders', async () => {
    stubServer({
      roles: ['author'],
      workflows: [
        { id: 'b', name: 'B', folder: 'Zeta' },
        { id: 'a', name: 'A', folder: null },
        { id: 'c', name: 'C', folder: 'Alpha' },
      ],
    })
    const tree = await loadWorkflowTree()
    expect(tree.map((node) => node.label)).toEqual(['Alpha', 'Zeta', 'Unfiled'])
    expect(tree[2]?.children?.[0]?.to).toBe('/studio/workflows/a')

    stubServer({ roles: ['author'], workflows: [{ id: 'x', name: 'X', folder: null }] })
    expect((await loadWorkflowTree()).map((node) => node.label)).toEqual(['X'])
  })
})

describe('command palette', () => {
  it('opens with Ctrl+K, filters, and runs a command with the keyboard only', async () => {
    const { router } = await mountApp('/operations', { roles: ['admin'] })
    const search = wrapper!.get('button.shell__search').element as HTMLElement
    search.focus()

    press(document.activeElement!, 'k', { ctrlKey: true })
    await settle()
    const dialog = wrapper!.get('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    const input = wrapper!.get('input[role="combobox"]')
    expect(document.activeElement).toBe(input.element)
    expect(wrapper!.get('.shell__frame').attributes('inert')).toBeDefined()

    await input.setValue('inbox')
    const options = wrapper!.findAll('[role="option"]')
    expect(options[0]?.text()).toContain('Go to Inbox')
    expect(input.attributes('aria-activedescendant')).toBe(options[0]?.attributes('id'))

    // Tab stays inside the dialog.
    press(input.element, 'Tab')
    expect(document.activeElement).toBe(input.element)

    press(input.element, 'Enter')
    await settle()
    expect(router.currentRoute.value.path).toBe('/inbox')
    expect(wrapper!.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(search)
  })

  it('moves with the arrow keys and closes with Escape, returning focus', async () => {
    await mountApp('/operations', { roles: ['admin'] })
    const search = wrapper!.get('button.shell__search')
    ;(search.element as HTMLElement).focus()
    await search.trigger('click')
    await settle()
    const input = wrapper!.get('input[role="combobox"]')
    await input.setValue('theme')
    const ids = wrapper!.findAll('[role="option"]').map((option) => option.attributes('id'))
    press(input.element, 'ArrowDown')
    await settle()
    expect(input.attributes('aria-activedescendant')).toBe(ids[1])
    press(input.element, 'ArrowUp')
    press(input.element, 'ArrowUp')
    await settle()
    expect(input.attributes('aria-activedescendant')).toBe(ids.at(-1))

    press(input.element, 'Escape')
    await settle()
    expect(wrapper!.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(search.element)
  })

  it('offers only the commands the role allows', async () => {
    await mountApp('/operations', { roles: ['viewer'] })
    press(document.body, 'k', { metaKey: true })
    await settle()
    await wrapper!.get('input[role="combobox"]').setValue('admin')
    expect(wrapper!.findAll('[role="option"]').map((o) => o.text())).not.toContain('Go to Admin')
  })

  it('ranks label matches first and needs every word to match', () => {
    const run = () => undefined
    const commands: PaletteCommand[] = [
      { id: 'a', label: 'Sign out', group: 'Account', keywords: ['theme'], run },
      { id: 'b', label: 'Theme: Dark', group: 'Preferences', run },
      { id: 'c', label: 'Go to Studio', group: 'Navigation', run },
    ]
    expect(filterCommands(commands, 'theme').map((c) => c.id)).toEqual(['b', 'a'])
    expect(filterCommands(commands, 'go studio').map((c) => c.id)).toEqual(['c'])
    expect(filterCommands(commands, '  ')).toHaveLength(3)
    expect(filterCommands(commands, 'nothing')).toEqual([])
  })
})

describe('breadcrumbs', () => {
  it('follows route meta, links parents and marks the current page', async () => {
    const { router } = await mountApp('/studio/workflows/wf-7', { roles: ['author'] })
    const crumbs = wrapper!.get('nav[aria-label="Breadcrumb"]')
    expect(crumbs.get('a').text()).toBe('Studio')
    expect(crumbs.get('a').attributes('href')).toBe('/studio')
    expect(crumbs.get('[aria-current="page"]').text()).toBe('wf-7')
    expect(document.title).toBe('wf-7 - WorkTree')

    await router.push('/operations')
    await settle()
    expect(wrapper!.get('nav[aria-label="Breadcrumb"] [aria-current="page"]').text()).toBe('Operations')
  })

  it('lets a page name its own crumb while mounted', async () => {
    const { router } = await mountApp('/studio/workflows/wf-7', { roles: ['author'] })
    const Page = defineComponent({
      setup() {
        useCrumbLabel(() => 'Bank reconciliation')
        return () => h('div')
      },
    })
    const page = mount(Page)
    expect(breadcrumbsFor(router.currentRoute.value, 'Bank reconciliation').at(-1)?.label).toBe('Bank reconciliation')
    await settle()
    expect(wrapper!.get('nav[aria-label="Breadcrumb"] [aria-current="page"]').text()).toBe('Bank reconciliation')
    page.unmount()
    await settle()
    expect(wrapper!.get('nav[aria-label="Breadcrumb"] [aria-current="page"]').text()).toBe('wf-7')
  })
})

describe('toasts and message bars', () => {
  it('announces through live regions that exist before any toast, and closes by itself', async () => {
    await mountApp('/operations', { roles: ['viewer'] })
    const polite = wrapper!.get('.toasts [role="status"]')
    const urgent = wrapper!.get('.toasts [role="alert"]')
    expect(polite.attributes('aria-live')).toBe('polite')
    expect(urgent.attributes('aria-live')).toBe('assertive')
    expect(polite.text()).toBe('')

    vi.useFakeTimers()
    const toast = useToast()
    toast.success('Saved version 3')
    toast.error('Run failed to start')
    await flushPromises()
    expect(polite.text()).toContain('Saved version 3')
    expect(urgent.text()).toContain('Run failed to start')

    vi.advanceTimersByTime(5_000)
    await flushPromises()
    expect(polite.text()).toBe('')
    expect(urgent.text()).toContain('Run failed to start')

    await urgent.get('button[aria-label="Dismiss notification"]').trigger('click')
    expect(urgent.text()).toBe('')
  })

  it('pauses while hovered', async () => {
    await mountApp('/operations', { roles: ['viewer'] })
    vi.useFakeTimers()
    useToast().info('Copied')
    await flushPromises()
    const item = wrapper!.get('.toast')
    await item.trigger('mouseenter')
    vi.advanceTimersByTime(10_000)
    await flushPromises()
    expect(wrapper!.find('.toast').exists()).toBe(true)
    await item.trigger('mouseleave')
    vi.advanceTimersByTime(5_000)
    await flushPromises()
    expect(wrapper!.find('.toast').exists()).toBe(false)
  })

  it('uses alert for errors and status for information', () => {
    expect(mount(MessageBar, { props: { intent: 'error' }, slots: { default: 'Bad' } }).attributes('role')).toBe('alert')
    const info = mount(MessageBar, { props: { intent: 'info', dismissible: true }, slots: { default: 'Note' } })
    expect(info.attributes('role')).toBe('status')
    void info.get('button[aria-label="Dismiss message"]').trigger('click')
    expect(info.emitted('dismiss')).toHaveLength(1)
  })
})

describe('login', () => {
  async function fill(username: string, password: string): Promise<void> {
    const [user, pass] = wrapper!.findAll('input.u-control')
    for (const [field, value] of [
      [user, username],
      [pass, password],
    ] as const) {
      ;(field!.element as HTMLInputElement).value = value
      await field!.trigger('input')
    }
  }

  it('signs in and continues to the page that was asked for', async () => {
    const { router } = await mountApp('/data', {
      roles: null,
      login: (body) => (body.password === 'pw' ? json(200, me(['viewer'])) : json(401, { error: { code: 'unauthorized', message: 'x' } })),
    })
    expect(router.currentRoute.value.name).toBe('login')
    const [user, pass] = wrapper!.findAll('input.u-control')
    expect(user!.attributes('autocomplete')).toBe('username')
    expect(pass!.attributes('autocomplete')).toBe('current-password')
    await fill('ada', 'pw')
    await wrapper!.get('form').trigger('submit')
    await settle()
    expect(router.currentRoute.value.path).toBe('/data')
    expect(wrapper!.get('.user-menu__name').text()).toBe('Ada Lovelace')
  })

  it('shows an error and clears the password on failure', async () => {
    await mountApp('/login', { roles: null, login: () => json(401, { error: { code: 'unauthorized', message: 'x' } }) })
    await fill('ada', 'wrong')
    await wrapper!.get('form').trigger('submit')
    await settle()
    expect(wrapper!.get('[role="alert"].message-bar').text()).toBe('The username or password is incorrect.')
    expect((wrapper!.findAll('input.u-control')[1]!.element as HTMLInputElement).value).toBe('')
  })

  it('asks for both fields before calling the server', async () => {
    const { fetchMock } = await mountApp('/login', { roles: null })
    await wrapper!.get('form').trigger('submit')
    expect(wrapper!.text()).toContain('Enter your username and password.')
    expect(fetchMock).not.toHaveBeenCalledWith('/api/auth/login', expect.anything())
  })
})

describe('user menu', () => {
  it('switches theme and density by keyboard and signs out with the CSRF token', async () => {
    const { router, fetchMock } = await mountApp('/operations', { roles: ['viewer'] })
    const trigger = wrapper!.get('.user-menu__trigger')
    press(trigger.element, 'ArrowDown')
    await settle()
    expect(trigger.attributes('aria-expanded')).toBe('true')
    const items = () => wrapper!.findAll('[role^="menuitem"]')
    expect(document.activeElement).toBe(items()[0]!.element)

    press(document.activeElement!, 'ArrowDown')
    press(document.activeElement!, 'ArrowDown')
    expect(document.activeElement?.textContent?.trim()).toBe('Dark')
    ;(document.activeElement as HTMLElement).click()
    await settle()
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(items()[2]!.attributes('aria-checked')).toBe('true')

    press(document.activeElement!, 'Escape')
    await settle()
    expect(wrapper!.find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)

    await trigger.trigger('click')
    press(document.activeElement!, 'End')
    expect(document.activeElement?.textContent?.trim()).toBe('Sign out')
    ;(document.activeElement as HTMLElement).click()
    await settle()
    const logout = fetchMock.mock.calls.find(([url]) => url === '/api/auth/logout')
    expect((logout?.[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok-1')
    expect(router.currentRoute.value.name).toBe('login')
  })
})

describe('api client CSRF', () => {
  it('falls back to the readable CSRF cookie', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    setCsrfToken(null)
    document.cookie = 'uaf_csrf=from-cookie'
    await apiSend('POST', '/api/x', {})
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({ 'X-CSRF-Token': 'from-cookie' })
    document.cookie = 'uaf_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })
})
