import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, type Ref } from 'vue'
import { buildUrl } from '@/api/client'
import type { LiveEvent, useLiveEvents as UseLiveEvents } from '@/api/live'
import BoardView from '@/components/BoardView.vue'
import CodeBlock from '@/components/CodeBlock.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DataTable from '@/components/DataTable.vue'
import FilterBar from '@/components/FilterBar.vue'
import LoadState from '@/components/LoadState.vue'
import RelativeTime from '@/components/RelativeTime.vue'
import UDialog from '@/components/UDialog.vue'
import UPagination from '@/components/UPagination.vue'
import USelect from '@/components/USelect.vue'
import UTabs from '@/components/UTabs.vue'
import UTextArea from '@/components/UTextArea.vue'
import { formatCount, formatDateTime } from '@/format'
import { useToastStore } from '@/stores/toast'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

interface Row {
  id: string
  name: string
  count: number | null
}

const COLUMNS = [
  { key: 'name', label: 'Name', sortable: true },
  { key: 'count', label: 'Count', align: 'end' as const },
]
const ROWS: Row[] = [
  { id: 'a', name: 'Alpha', count: 1 },
  { id: 'b', name: 'Beta', count: null },
  { id: 'c', name: 'Gamma', count: 3 },
]

function mountTable(props: Record<string, unknown> = {}, slots: Record<string, string> = {}) {
  return mount(DataTable, {
    attachTo: document.body,
    props: { columns: COLUMNS, rows: ROWS, rowKey: (row: unknown) => (row as Row).id, caption: 'Items', ...props },
    slots,
  })
}

describe('DataTable', () => {
  it('renders a captioned native table with text cells and a dash for missing values', () => {
    const table = mountTable()
    expect(table.get('caption').text()).toBe('Items')
    const cells = table.findAll('tbody tr')[1]?.findAll('td')
    expect(cells?.[0]?.text()).toBe('Beta')
    expect(cells?.[1]?.text()).toBe('-')
    expect(table.findAll('th')[1]?.classes()).toContain('data-table__cell--end')
  })

  it('renders cell slots with the row and value', () => {
    const table = mountTable({}, { 'cell-name': '<template #cell-name="{ row, value }"><b>{{ value }}:{{ row.id }}</b></template>' })
    expect(table.find('tbody b').text()).toBe('Alpha:a')
  })

  it('toggles sort to descending, then ascending, and reflects it in aria-sort', async () => {
    const table = mountTable({ sort: 'created_at', 'onUpdate:sort': (sort: string) => table.setProps({ sort }) })
    const header = table.findAll('th')[0]
    expect(header?.attributes('aria-sort')).toBe('none')
    expect(table.findAll('th')[1]?.attributes('aria-sort')).toBeUndefined()

    await header?.get('button').trigger('click')
    expect(table.emitted('update:sort')?.[0]).toEqual(['-name'])
    expect(header?.attributes('aria-sort')).toBe('descending')

    await header?.get('button').trigger('click')
    expect(table.emitted('update:sort')?.[1]).toEqual(['name'])
    expect(header?.attributes('aria-sort')).toBe('ascending')

    await header?.get('button').trigger('click')
    expect(table.emitted('update:sort')?.[2]).toEqual(['-name'])
  })

  it('keeps rows out of the tab order when they cannot be opened', async () => {
    const table = mountTable()
    const row = table.find('tbody tr')
    expect(row.attributes('tabindex')).toBeUndefined()
    await row.trigger('click')
    await row.trigger('keydown', { key: 'Enter' })
    expect(table.emitted('row-open')).toBeUndefined()
  })

  it('makes rows one tab stop, opens on click or Enter and moves with the arrow keys', async () => {
    const onRowOpen = vi.fn()
    const table = mountTable({ onRowOpen })
    const rows = table.findAll('tbody tr')
    expect(rows.map((row) => row.attributes('tabindex'))).toEqual(['0', '-1', '-1'])

    await rows[0]?.trigger('click')
    expect(onRowOpen).toHaveBeenLastCalledWith(ROWS[0])
    await rows[1]?.trigger('keydown', { key: 'Enter' })
    expect(onRowOpen).toHaveBeenLastCalledWith(ROWS[1])

    ;(rows[0]?.element as HTMLElement).focus()
    await rows[0]?.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(rows[1]?.element)
    expect(rows.map((row) => row.attributes('tabindex'))).toEqual(['-1', '0', '-1'])
    await rows[1]?.trigger('keydown', { key: 'ArrowUp' })
    expect(document.activeElement).toBe(rows[0]?.element)
    await rows[0]?.trigger('keydown', { key: 'ArrowUp' })
    expect(document.activeElement).toBe(rows[0]?.element)
  })

  it('leaves clicks and keys on controls inside a cell alone', async () => {
    const onRowOpen = vi.fn()
    const table = mountTable({ onRowOpen }, { 'cell-name': '<button class="inner">Run</button>' })
    await table.get('.inner').trigger('click')
    await table.get('.inner').trigger('keydown', { key: 'Enter' })
    expect(onRowOpen).not.toHaveBeenCalled()
  })

  it('marks the selected row, makes it the tab stop and uses the row label', () => {
    const table = mountTable({ selectedKey: 'b', rowLabel: (row: unknown) => `Open ${(row as Row).name}` })
    const rows = table.findAll('tbody tr')
    expect(rows[1]?.classes()).toContain('data-table__row--selected')
    expect(rows[1]?.attributes('aria-current')).toBe('true')
    expect(rows[1]?.attributes('tabindex')).toBe('0')
    expect(rows[1]?.attributes('aria-label')).toBe('Open Beta')
    expect(rows[0]?.attributes('aria-current')).toBeUndefined()
  })
})

describe('UPagination', () => {
  function mountPager(offset: number, total = 230, limit = 50) {
    return mount(UPagination, { props: { total, limit, offset } })
  }

  it('renders nothing when one page holds everything', () => {
    expect(mountPager(0, 50, 50).find('nav').exists()).toBe(false)
  })

  it('shows the range and disables previous on the first page', async () => {
    const pager = mountPager(0)
    expect(pager.text()).toContain('1-50 of 230')
    const [previous, next] = pager.findAll('fluent-button')
    expect(previous?.attributes('aria-label')).toBe('Previous page')
    expect(previous?.attributes('disabled')).toBeDefined()
    expect(next?.attributes('aria-label')).toBe('Next page')
    expect(next?.attributes('disabled')).toBeUndefined()
    await previous?.trigger('click')
    expect(pager.emitted('update:offset')).toBeUndefined()
    await next?.trigger('click')
    expect(pager.emitted('update:offset')?.[0]).toEqual([50])
  })

  it('caps the range and disables next on the last page', async () => {
    const pager = mountPager(200)
    expect(pager.text()).toContain('201-230 of 230')
    const [previous, next] = pager.findAll('fluent-button')
    expect(next?.attributes('disabled')).toBeDefined()
    await next?.trigger('click')
    expect(pager.emitted('update:offset')).toBeUndefined()
    await previous?.trigger('click')
    expect(pager.emitted('update:offset')?.[0]).toEqual([150])
  })
})

describe('USelect', () => {
  const options = [
    { value: 'a', label: 'Alpha' },
    { value: 'b', label: 'Beta' },
  ]

  it('renders the options and marks the selected one', () => {
    const select = mount(USelect, { props: { label: 'State', options, modelValue: 'b', placeholder: 'Pick one' } })
    expect(select.text()).toContain('State')
    expect(select.get('fluent-dropdown').attributes('placeholder')).toBe('Pick one')
    const items = select.findAll('fluent-listbox fluent-option')
    expect(items.map((item) => item.attributes('value'))).toEqual(['a', 'b'])
    expect(items[0]?.attributes('selected')).toBeUndefined()
    expect(items[1]?.attributes('selected')).toBeDefined()
  })

  it('is not wrapped in a label, which would reopen it after a pick', () => {
    expect(mount(USelect, { props: { label: 'State', options } }).find('label').exists()).toBe(false)
  })

  it('updates the model from the change event', async () => {
    const select = mount(USelect, { props: { label: 'State', options, modelValue: 'a' } })
    const dropdown = select.get('fluent-dropdown')
    ;(dropdown.element as HTMLInputElement).value = 'b'
    await dropdown.trigger('change')
    expect(select.emitted('update:modelValue')?.[0]).toEqual(['b'])
  })

  it('names the combobox Fluent renders after mount and passes disabled', async () => {
    const select = mount(USelect, { props: { label: 'State', options, disabled: true } })
    const dropdown = select.get('fluent-dropdown')
    expect(dropdown.attributes('disabled')).toBeDefined()
    const control = document.createElement('button')
    control.setAttribute('role', 'combobox')
    dropdown.element.prepend(control)
    await flushPromises()
    expect(control.getAttribute('aria-labelledby')).toBe(select.get('.u-field__label').attributes('id'))
  })

  it('keeps Escape from reaching a dialog only while the list is open', async () => {
    const select = mount(USelect, { props: { label: 'State', options } })
    const dropdown = select.get('fluent-dropdown')
    const press = () => {
      const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
      dropdown.element.dispatchEvent(event)
      return event.defaultPrevented
    }
    expect(press()).toBe(false)
    ;(dropdown.element as HTMLElement & { open: boolean }).open = true
    expect(press()).toBe(true)
  })
})

describe('UTextArea', () => {
  it('updates its model, labels itself through the Fluent slot and sizes by rows', async () => {
    const area = mount(UTextArea, { props: { label: 'Notes', modelValue: '', rows: 5, required: true } })
    const element = area.get('fluent-textarea')
    expect(area.get('[slot="label"]').text()).toBe('Notes')
    expect(element.attributes('required')).toBeDefined()
    expect(element.attributes('style')).toContain('calc(5 *')
    ;(element.element as HTMLTextAreaElement).value = 'hello'
    await element.trigger('input')
    expect(area.emitted('update:modelValue')?.[0]).toEqual(['hello'])
  })

  it('passes the first value as default-slot text, which Fluent keeps once connected', async () => {
    const area = mount(UTextArea, { props: { label: 'Notes', modelValue: 'first' } })
    const element = area.get('fluent-textarea')
    expect(element.element.childNodes[element.element.childNodes.length - 1]?.textContent?.trim()).toBe('first')
    await area.setProps({ modelValue: 'second' })
    expect((element.element as HTMLTextAreaElement).value ?? element.attributes('value')).toBe('second')
    expect(element.text()).not.toContain('second')
  })

  it('defaults to three rows', () => {
    const area = mount(UTextArea, { props: { label: 'Notes' } })
    expect(area.get('fluent-textarea').attributes('style')).toContain('calc(3 *')
  })
})

describe('UDialog', () => {
  function stubbedDialog(props: Record<string, unknown> = {}) {
    const dialog = mount(UDialog, {
      attachTo: document.body,
      props: { title: 'Edit', ...props },
      slots: { default: '<p>Body</p>', footer: '<button>Save</button>' },
    })
    const element = dialog.get('fluent-dialog').element as HTMLElement & { show: () => void; hide: () => void }
    element.show = vi.fn()
    element.hide = vi.fn()
    return { dialog, element }
  }

  it('names the dialog, sizes it and places the body and footer', () => {
    const dialog = mount(UDialog, { props: { title: 'Edit', size: 'large' }, slots: { default: '<p>Body</p>', footer: '<button>Save</button>' } })
    const element = dialog.get('fluent-dialog')
    expect(element.attributes('aria-label')).toBe('Edit')
    expect(element.classes()).toContain('u-dialog--large')
    expect(dialog.get('[slot="title"]').text()).toBe('Edit')
    expect(dialog.get('fluent-dialog-body').text()).toContain('Body')
    expect(dialog.get('[slot="action"]').text()).toBe('Save')
  })

  it('uses the medium size and leaves out an empty footer by default', () => {
    const dialog = mount(UDialog, { props: { title: 'Edit' } })
    expect(dialog.get('fluent-dialog').classes()).toContain('u-dialog--medium')
    expect(dialog.find('[slot="action"]').exists()).toBe(false)
  })

  it('shows on open and hides on close, returning focus', async () => {
    const trigger = document.body.appendChild(document.createElement('button'))
    trigger.focus()
    const { dialog, element } = stubbedDialog()
    await dialog.setProps({ open: true })
    expect(element.show).toHaveBeenCalledOnce()
    ;(dialog.get('fluent-dialog-body').element as HTMLElement).tabIndex = -1
    ;(dialog.get('fluent-dialog-body').element as HTMLElement).focus()
    await dialog.setProps({ open: false })
    expect(element.hide).toHaveBeenCalledOnce()
    expect(document.activeElement).toBe(trigger)
  })

  it('opens at mount when open is already true', () => {
    const show = vi.fn()
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'show')
    Object.defineProperty(HTMLElement.prototype, 'show', { configurable: true, value: show })
    mount(UDialog, { props: { title: 'Edit', open: true } })
    expect(show).toHaveBeenCalledOnce()
    if (original) Object.defineProperty(HTMLElement.prototype, 'show', original)
    else delete (HTMLElement.prototype as unknown as { show?: unknown }).show
  })

  it('sets open to false from the close button and Escape', async () => {
    const closing = stubbedDialog({ open: false })
    await closing.dialog.setProps({ open: true })
    await closing.dialog.get('[slot="close"]').trigger('click')
    expect(closing.dialog.emitted('update:open')?.[0]).toEqual([false])

    const escaping = stubbedDialog()
    await escaping.dialog.setProps({ open: true })
    await escaping.dialog.get('fluent-dialog').trigger('keydown', { key: 'Escape' })
    expect(escaping.dialog.emitted('update:open')?.[0]).toEqual([false])
  })

  it('does not close on an Escape a child already handled', async () => {
    const { dialog } = stubbedDialog()
    await dialog.setProps({ open: true })
    dialog.get('fluent-dialog-body').element.addEventListener('keydown', (event) => event.preventDefault())
    await dialog.get('fluent-dialog-body').trigger('keydown', { key: 'Escape' })
    expect(dialog.emitted('update:open')).toBeUndefined()
  })

  it('follows a close made by Fluent without hiding twice', async () => {
    const { dialog, element } = stubbedDialog()
    await dialog.setProps({ open: true })
    element.dispatchEvent(new CustomEvent('toggle', { detail: { newState: 'closed' } }))
    expect(dialog.emitted('update:open')?.[0]).toEqual([false])
    await dialog.setProps({ open: false })
    expect(element.hide).not.toHaveBeenCalled()
  })

  it('ignores a toggle bubbling up from something inside', async () => {
    const { dialog } = stubbedDialog()
    await dialog.setProps({ open: true })
    dialog.get('fluent-dialog-body').element.dispatchEvent(new CustomEvent('toggle', { bubbles: true, detail: { newState: 'closed' } }))
    expect(dialog.emitted('update:open')).toBeUndefined()
  })

  it('returns focus when unmounted while open', async () => {
    const trigger = document.body.appendChild(document.createElement('button'))
    trigger.focus()
    const { dialog } = stubbedDialog()
    await dialog.setProps({ open: true })
    ;(dialog.get('fluent-dialog-body').element as HTMLElement).tabIndex = -1
    ;(dialog.get('fluent-dialog-body').element as HTMLElement).focus()
    dialog.unmount()
    expect(document.activeElement).toBe(trigger)
  })
})

describe('ConfirmDialog', () => {
  const base = { title: 'Reject task', message: 'This cannot be undone.', confirmLabel: 'Reject task', open: true }

  function confirmButton(dialog: VueWrapper) {
    return dialog.get('[appearance="primary"]')
  }

  async function typeReason(dialog: VueWrapper, text: string) {
    const area = dialog.get('fluent-textarea')
    ;(area.element as HTMLTextAreaElement).value = text
    await area.trigger('input')
  }

  it('confirms with an empty reason when none is asked for and does not close itself', async () => {
    const dialog = mount(ConfirmDialog, { props: base })
    expect(dialog.text()).toContain('This cannot be undone.')
    expect(dialog.find('fluent-textarea').exists()).toBe(false)
    await confirmButton(dialog).trigger('click')
    expect(dialog.emitted('confirm')?.[0]).toEqual([''])
    expect(dialog.emitted('update:open')).toBeUndefined()
  })

  it('blocks confirm until a required reason is given, and trims it', async () => {
    const dialog = mount(ConfirmDialog, { props: { ...base, reasonLabel: 'Reason', reasonRequired: true } })
    expect(confirmButton(dialog).attributes('disabled')).toBeDefined()
    await typeReason(dialog, '   ')
    expect(confirmButton(dialog).attributes('disabled')).toBeDefined()
    await typeReason(dialog, '  duplicate  ')
    expect(confirmButton(dialog).attributes('disabled')).toBeUndefined()
    await confirmButton(dialog).trigger('click')
    expect(dialog.emitted('confirm')?.[0]).toEqual(['duplicate'])
  })

  it('allows a blank reason when it is optional, and ignores reasonRequired without a field', () => {
    const optional = mount(ConfirmDialog, { props: { ...base, reasonLabel: 'Reason' } })
    expect(confirmButton(optional).attributes('disabled')).toBeUndefined()
    const noField = mount(ConfirmDialog, { props: { ...base, reasonRequired: true } })
    expect(confirmButton(noField).attributes('disabled')).toBeUndefined()
  })

  it('disables confirm while busy', () => {
    const dialog = mount(ConfirmDialog, { props: { ...base, busy: true } })
    expect(confirmButton(dialog).attributes('disabled')).toBeDefined()
  })

  it('uses the primary appearance for a danger confirm', () => {
    const dialog = mount(ConfirmDialog, { props: { ...base, danger: true } })
    expect(confirmButton(dialog).text()).toBe('Reject task')
  })

  it('cancels and starts blank when reopened', async () => {
    const dialog = mount(ConfirmDialog, { props: { ...base, reasonLabel: 'Reason', reasonRequired: true } })
    await typeReason(dialog, 'first')
    await dialog.findAll('fluent-dialog-body [slot="action"] fluent-button')[0]?.trigger('click')
    expect(dialog.emitted('update:open')?.[0]).toEqual([false])
    await dialog.setProps({ open: false })
    await dialog.setProps({ open: true })
    expect(confirmButton(dialog).attributes('disabled')).toBeDefined()
  })
})

describe('UTabs', () => {
  const tabs = [{ id: 'a', label: 'All', count: 1200 }, { id: 'b', label: 'Mine' }, { id: 'c', label: 'Done' }]

  function mountTabs(modelValue = 'a') {
    const wrapper = mount(UTabs, {
      attachTo: document.body,
      props: { tabs, label: 'Filter', modelValue, 'onUpdate:modelValue': (value: string) => wrapper.setProps({ modelValue: value }) },
    })
    return wrapper
  }

  it('marks up a tablist with a roving tabindex and a plain count', () => {
    const wrapper = mountTabs('b')
    expect(wrapper.get('[role="tablist"]').attributes('aria-label')).toBe('Filter')
    const items = wrapper.findAll('[role="tab"]')
    expect(items.map((tab) => tab.attributes('aria-selected'))).toEqual(['false', 'true', 'false'])
    expect(items.map((tab) => tab.attributes('tabindex'))).toEqual(['-1', '0', '-1'])
    expect(items[0]?.get('.tabs__count').text()).toBe(formatCount(1200))
    expect(items[1]?.find('.tabs__count').exists()).toBe(false)
  })

  it('moves with the arrow keys, wrapping at the ends, and with Home and End', async () => {
    const wrapper = mountTabs()
    const items = wrapper.findAll('[role="tab"]')

    await items[0]?.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['b'])
    expect(document.activeElement).toBe(items[1]?.element)

    await items[0]?.trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['c'])
    expect(document.activeElement).toBe(items[2]?.element)

    await items[2]?.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['a'])

    await items[0]?.trigger('keydown', { key: 'End' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['c'])

    await items[2]?.trigger('keydown', { key: 'Home' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['a'])
    expect(document.activeElement).toBe(items[0]?.element)
  })

  it('selects on click and keeps a tab stop for an unknown value', async () => {
    const wrapper = mountTabs('nope')
    expect(wrapper.findAll('[role="tab"]')[0]?.attributes('tabindex')).toBe('0')
    await wrapper.findAll('[role="tab"]')[2]?.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['c'])
  })
})

describe('FilterBar', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  async function type(bar: VueWrapper, text: string) {
    const input = bar.get('fluent-text-input')
    ;(input.element as HTMLInputElement).value = text
    await input.trigger('input')
  }

  it('leaves out the search field without a label and the clear button unless active', () => {
    const bar = mount(FilterBar, { slots: { default: '<span class="control" />' } })
    expect(bar.find('fluent-text-input').exists()).toBe(false)
    expect(bar.find('fluent-button').exists()).toBe(false)
    expect(bar.find('.control').exists()).toBe(true)
  })

  it('debounces the search model by 250 ms, restarting on each keystroke', async () => {
    const bar = mount(FilterBar, { props: { searchLabel: 'Search' } })
    await type(bar, 'a')
    vi.advanceTimersByTime(200)
    await type(bar, 'ab')
    vi.advanceTimersByTime(249)
    expect(bar.emitted('update:search')).toBeUndefined()
    vi.advanceTimersByTime(1)
    expect(bar.emitted('update:search')).toEqual([['ab']])
  })

  it('emits clear, drops pending input and follows the model from outside', async () => {
    const bar = mount(FilterBar, { props: { searchLabel: 'Search', active: true, search: 'old' } })
    await type(bar, 'pending')
    await bar.get('fluent-button').trigger('click')
    expect(bar.emitted('clear')).toHaveLength(1)
    vi.advanceTimersByTime(1_000)
    expect(bar.emitted('update:search')).toEqual([['']])
    await bar.setProps({ search: 'fresh' })
    expect((bar.get('fluent-text-input').element as HTMLInputElement).value).toBe('fresh')
  })

  it('cancels the debounce on unmount', async () => {
    const bar = mount(FilterBar, { props: { searchLabel: 'Search' } })
    await type(bar, 'a')
    bar.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('LoadState', () => {
  function mountState(props: Record<string, unknown>) {
    return mount(LoadState, { props, slots: { default: '<p class="content">Content</p>' } })
  }

  it('shows loading above everything else', () => {
    const state = mountState({ loading: true, error: new Error('Boom'), empty: true, emptyTitle: 'None' })
    expect(state.get('[role="status"]').text()).toBe('Loading...')
    expect(state.text()).not.toContain('Boom')
    expect(state.text()).not.toContain('None')
  })

  it('shows the error above empty, with a retry', async () => {
    const state = mountState({ error: new Error('Boom'), empty: true, emptyTitle: 'None' })
    expect(state.get('[role="alert"]').text()).toContain('Boom')
    expect(state.text()).not.toContain('None')
    await state.get('fluent-button').trigger('click')
    expect(state.emitted('retry')).toHaveLength(1)
  })

  it('falls back to a generic message for an unknown error', () => {
    expect(mountState({ error: { status: 500 } }).get('[role="alert"]').text()).toContain('Something went wrong.')
    expect(mountState({ error: 'Offline' }).get('[role="alert"]').text()).toContain('Offline')
  })

  it('shows the empty state above the content', () => {
    const state = mountState({ empty: true, emptyTitle: 'None', emptyDescription: 'Create one.' })
    expect(state.get('h2').text()).toBe('None')
    expect(state.text()).toContain('Create one.')
    expect(state.find('.content').exists()).toBe(false)
  })

  it('renders the content otherwise', () => {
    expect(mountState({}).find('.content').exists()).toBe(true)
  })
})

describe('RelativeTime', () => {
  const NOW = new Date('2026-06-15T12:00:00Z')
  const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString()
  const MINUTE = 60_000
  const HOUR = 60 * MINUTE
  const DAY = 24 * HOUR

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })

  it.each([
    [10_000, 'just now'],
    [3 * MINUTE, '3 min ago'],
    [2 * HOUR, '2 h ago'],
    [4 * DAY, '4 d ago'],
    [30 * DAY, '30 d ago'],
  ])('renders an age of %i ms as "%s"', (age, expected) => {
    expect(mount(RelativeTime, { props: { value: ago(age) } }).text()).toBe(expected)
  })

  it('switches to a short date after 30 days and holds the full time in the title', () => {
    const value = ago(31 * DAY)
    const time = mount(RelativeTime, { props: { value } })
    expect(time.element.tagName).toBe('TIME')
    expect(time.text()).not.toContain('ago')
    expect(time.text()).toContain('2026')
    expect(time.attributes('datetime')).toBe(value)
    expect(time.attributes('title')).toBe(formatDateTime(value))
  })

  it('shows a dash when the value is absent or invalid', () => {
    for (const value of [null, undefined, 'not a date']) {
      const time = mount(RelativeTime, { props: { value } })
      expect(time.text()).toBe('-')
      expect(time.attributes('title')).toBeUndefined()
    }
  })

  it('updates every 30 s and clears its timer on unmount', async () => {
    const time = mount(RelativeTime, { props: { value: ago(10_000) } })
    expect(time.text()).toBe('just now')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(time.text()).toBe('1 min ago')
    expect(vi.getTimerCount()).toBe(1)
    time.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('CodeBlock', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders focusable labelled text', () => {
    const block = mount(CodeBlock, { props: { text: 'line one', label: 'Step output', wrap: true } })
    const pre = block.get('pre')
    expect(pre.text()).toBe('line one')
    expect(pre.attributes('tabindex')).toBe('0')
    expect(pre.attributes('aria-label')).toBe('Step output')
    expect(pre.classes()).toContain('code-block__text--wrap')
  })

  it('copies and confirms with a toast', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const block = mount(CodeBlock, { props: { text: 'copy me', label: 'Output' } })
    await block.get('fluent-button').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('copy me')
    expect(useToastStore().toasts[0]).toMatchObject({ intent: 'success' })
  })

  it('reports a failed copy, including when the clipboard is unavailable', async () => {
    vi.stubGlobal('navigator', {})
    const block = mount(CodeBlock, { props: { text: 'copy me', label: 'Output' } })
    await block.get('fluent-button').trigger('click')
    await flushPromises()
    expect(useToastStore().toasts[0]).toMatchObject({ intent: 'error' })
  })
})

describe('BoardView', () => {
  it('renders each column with a plain count and the card slot', () => {
    const board = mount(BoardView, {
      props: {
        columns: [
          { id: 'todo', title: 'To do', items: [{ id: '1', name: 'First' }, { id: '2', name: 'Second' }] },
          { id: 'done', title: 'Done', items: [] },
        ],
        itemKey: (item: unknown) => (item as { id: string }).id,
      },
      slots: { default: '<template #default="{ item }"><article>{{ item.name }}</article></template>' },
    })
    const columns = board.findAll('section')
    expect(columns[0]?.get('.board__title').text()).toBe('To do')
    expect(columns[0]?.get('.board__count').text()).toBe('2')
    expect(columns[0]?.findAll('article').map((card) => card.text())).toEqual(['First', 'Second'])
    expect(columns[1]?.get('.board__count').text()).toBe('0')
  })
})

describe('format helpers', () => {
  it('formats dates and counts, with a dash for absent values', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime(undefined)).toBe('-')
    expect(formatDateTime('nonsense')).toBe('-')
    expect(formatDateTime('2026-06-15T12:00:00Z')).toContain('2026')
    expect(formatCount(1234567)).toBe(new Intl.NumberFormat().format(1234567))
  })
})

describe('buildUrl', () => {
  it('repeats the key for array values and leaves other values as they were', () => {
    expect(buildUrl('/api/runs', { query: { status: ['failed', 'cancelled'], limit: 50, skip: undefined, live: true } })).toBe(
      '/api/runs?status=failed&status=cancelled&limit=50&live=true',
    )
  })

  it('adds nothing for an empty array', () => {
    expect(buildUrl('/api/runs', { query: { status: [] } })).toBe('/api/runs')
  })
})

describe('live events', () => {
  class FakeSocket {
    static instances: FakeSocket[] = []
    onopen: (() => void) | null = null
    onmessage: ((message: { data: string }) => void) | null = null
    onclose: ((event: { code: number }) => void) | null = null
    closed = false

    constructor(readonly url: string) {
      FakeSocket.instances.push(this)
    }

    close(): void {
      this.closed = true
    }

    send(data: unknown): void {
      this.onmessage?.({ data: JSON.stringify(data) })
    }
  }

  const sockets = () => FakeSocket.instances
  const latest = () => FakeSocket.instances[FakeSocket.instances.length - 1] as FakeSocket
  let useLiveEvents: typeof UseLiveEvents

  function subscribe(handler: (event: LiveEvent) => void = () => undefined) {
    let connected!: Ref<boolean>
    const wrapper = mount(
      defineComponent({
        setup() {
          connected = useLiveEvents(handler).connected
          return () => h('div')
        },
      }),
    )
    return { wrapper, connected }
  }

  beforeEach(async () => {
    vi.useFakeTimers()
    FakeSocket.instances = []
    vi.stubGlobal('WebSocket', FakeSocket)
    vi.resetModules()
    useLiveEvents = (await import('@/api/live')).useLiveEvents
  })

  it('shares one socket on the same host, opened first and closed last', () => {
    const first = subscribe()
    const second = subscribe()
    expect(sockets()).toHaveLength(1)
    expect(latest().url).toBe(`ws://${window.location.host}/api/events`)
    first.wrapper.unmount()
    expect(latest().closed).toBe(false)
    second.wrapper.unmount()
    expect(latest().closed).toBe(true)
  })

  it('uses wss under https', () => {
    vi.stubGlobal('location', { protocol: 'https:', host: 'app.example' })
    subscribe()
    expect(latest().url).toBe('wss://app.example/api/events')
  })

  it('shares the connected state and passes events on, without ping and connected', () => {
    const received: LiveEvent[] = []
    const { connected } = subscribe((event) => received.push(event))
    const other = subscribe()
    expect(connected.value).toBe(false)
    latest().onopen?.()
    expect(connected.value).toBe(true)
    expect(other.connected).toBe(connected)

    latest().send({ type: 'connected', user: 'hope' })
    latest().send({ type: 'ping' })
    latest().onmessage?.({ data: 'not json' })
    latest().onmessage?.({ data: 'null' })
    latest().send({ type: 'run.finished', run_id: 'r1', status: 'done' })
    expect(received).toEqual([{ type: 'run.finished', run_id: 'r1', status: 'done' }])
  })

  it('stops calling a handler after its component unmounts', () => {
    const handler = vi.fn()
    const leaving = subscribe(handler)
    subscribe()
    leaving.wrapper.unmount()
    latest().send({ type: 'run.finished' })
    expect(handler).not.toHaveBeenCalled()
  })

  it('reconnects with backoff of 1, 2 and 4 s, capped at 30 s', () => {
    const { connected } = subscribe()
    latest().onopen?.()
    latest().onclose?.({ code: 1006 })
    expect(connected.value).toBe(false)

    for (const delay of [1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000]) {
      const count = sockets().length
      vi.advanceTimersByTime(delay - 1)
      expect(sockets()).toHaveLength(count)
      vi.advanceTimersByTime(1)
      expect(sockets()).toHaveLength(count + 1)
      latest().onclose?.({ code: 1006 })
    }
  })

  it('resets the backoff after a successful connection', () => {
    subscribe()
    latest().onclose?.({ code: 1006 })
    vi.advanceTimersByTime(1_000)
    latest().onclose?.({ code: 1006 })
    vi.advanceTimersByTime(2_000)
    latest().onopen?.()
    latest().onclose?.({ code: 1006 })
    const count = sockets().length
    vi.advanceTimersByTime(1_000)
    expect(sockets()).toHaveLength(count + 1)
  })

  it('does not reconnect after close code 1008', () => {
    subscribe()
    latest().onclose?.({ code: 1008 })
    vi.advanceTimersByTime(120_000)
    expect(sockets()).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not reconnect after a deliberate close, even when the close event arrives later', () => {
    const { wrapper } = subscribe()
    const socket = latest()
    wrapper.unmount()
    socket.onclose?.({ code: 1000 })
    vi.advanceTimersByTime(120_000)
    expect(sockets()).toHaveLength(1)
  })

  it('cancels a pending reconnect when the last subscriber leaves', () => {
    const { wrapper } = subscribe()
    latest().onclose?.({ code: 1006 })
    wrapper.unmount()
    vi.advanceTimersByTime(120_000)
    expect(sockets()).toHaveLength(1)
  })

  it('ignores a late close from a replaced socket', async () => {
    const first = subscribe()
    const old = latest()
    first.wrapper.unmount()
    const second = subscribe()
    latest().onopen?.()
    old.onclose?.({ code: 1006 })
    await nextTick()
    expect(second.connected.value).toBe(true)
    vi.advanceTimersByTime(120_000)
    expect(sockets()).toHaveLength(2)
  })
})
