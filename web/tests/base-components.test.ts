import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import PageHeader from '@/components/PageHeader.vue'
import PropertyList from '@/components/PropertyList.vue'
import RunTimeline from '@/components/RunTimeline.vue'
import UButton from '@/components/UButton.vue'
import UCheckbox from '@/components/UCheckbox.vue'
import USwitch from '@/components/USwitch.vue'
import UTextInput from '@/components/UTextInput.vue'
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
import { formatDuration, STATUS_NAMES, statusStyle } from '@/status'
import DesignView from '@/views/DesignView.vue'

afterEach(() => vi.unstubAllGlobals())

describe('status helpers', () => {
  it('lists every status and resolves each to a label', () => {
    expect(STATUS_NAMES).toContain('dispatched')
    for (const name of STATUS_NAMES) expect(statusStyle(name).label).not.toBe(name)
  })

  it('treats a name found on Object.prototype as an unknown status', () => {
    expect(statusStyle('constructor')).toEqual({ kind: 'neutral', label: 'constructor' })
  })

  it('never shows a full next unit before reaching it', () => {
    expect(formatDuration(999.6)).toBe('1.0 s')
    expect(formatDuration(9_999)).toBe('9.9 s')
    expect(formatDuration(59_999)).toBe('59 s')
    expect(formatDuration(3_599_999)).toBe('59 m 59 s')
  })

  it('shows a dash for a value that is not a finite duration', () => {
    expect(formatDuration(Number.POSITIVE_INFINITY)).toBe('-')
    expect(formatDuration(Number.NaN)).toBe('-')
  })
})

describe('UButton', () => {
  it('becomes an icon button when it has an icon and no text', () => {
    const button = mount(UButton, { props: { icon: 'copy', label: 'Copy' } })
    const element = button.get('button')
    expect(element.classes()).toContain('u-button--icon-only')
    expect(element.attributes('aria-label')).toBe('Copy')
    expect(element.attributes('title')).toBe('Copy')
    expect(element.attributes('type')).toBe('button')
  })

  it('puts the icon before the text', () => {
    const button = mount(UButton, { props: { icon: 'play' }, slots: { default: 'Run' } })
    expect(button.get('button').classes()).not.toContain('u-button--icon-only')
    expect(button.get('button').element.firstElementChild?.tagName.toLowerCase()).toBe('svg')
    expect(button.text()).toBe('Run')
  })

  it('stays focusable and busy while loading, and refuses clicks', async () => {
    const button = mount(UButton, { props: { loading: true }, slots: { default: 'Save' } })
    const element = button.get('button')
    expect(element.attributes('aria-disabled')).toBe('true')
    expect(element.attributes('disabled')).toBeUndefined()
    expect(element.attributes('aria-busy')).toBe('true')
    expect(button.find('.u-button__spinner').exists()).toBe(true)
    await element.trigger('click')
    expect(button.emitted('click')).toBeUndefined()
  })

  it('does not emit a click when disabled', async () => {
    const button = mount(UButton, { props: { disabled: true } })
    expect(button.get('button').attributes('disabled')).toBeDefined()
    await button.get('button').trigger('click')
    expect(button.emitted('click')).toBeUndefined()
  })
})

describe('UTextInput', () => {
  const inner = (wrapper: ReturnType<typeof mount>) => wrapper.get('input').element

  it('names the input with its own label', () => {
    const input = mount(UTextInput, { props: { label: 'Name' } })
    const label = input.get('label')
    expect(label.text()).toBe('Name')
    expect(label.attributes('for')).toBe(inner(input).id)
    expect(input.get('input').attributes('aria-label')).toBeUndefined()
  })

  it('describes the input with its help and error text, and marks it invalid', async () => {
    const input = mount(UTextInput, { props: { label: 'Name', description: 'Letters only.' } })
    const texts = () =>
      (inner(input).getAttribute('aria-describedby') ?? '').split(' ').filter(Boolean).map((id) => input.find(`[id="${id}"]`).text())
    expect(texts()).toEqual(['Letters only.'])
    expect(inner(input).hasAttribute('aria-invalid')).toBe(false)

    await input.setProps({ error: 'Remove the slash.' })
    await nextTick()
    expect(texts()).toEqual(['Remove the slash.', 'Letters only.'])
    expect(inner(input).getAttribute('aria-invalid')).toBe('true')
    expect(input.get('[role="alert"]').text()).toBe('Remove the slash.')
    expect(input.classes()).toContain('u-field--invalid')

    await input.setProps({ error: undefined, description: undefined })
    await nextTick()
    expect(inner(input).hasAttribute('aria-describedby')).toBe(false)
    expect(inner(input).hasAttribute('aria-invalid')).toBe(false)
    expect(input.find('[role="alert"]').exists()).toBe(false)
  })

  it('passes required and read-only, and marks required for sighted users only', () => {
    const input = mount(UTextInput, { props: { label: 'Name', required: true, readonly: true } })
    const element = input.get('input')
    expect(element.attributes('required')).toBeDefined()
    expect(element.attributes('readonly')).toBeDefined()
    expect(input.get('.u-field__required').attributes('aria-hidden')).toBe('true')
  })
})

describe.each([
  ['UCheckbox', UCheckbox, 'input[type="checkbox"]:not([role])'],
  ['USwitch', USwitch, 'input[type="checkbox"][role="switch"]'],
] as const)('%s', (_name, component, tag) => {
  it('ties help and error text to the control by id', () => {
    const wrapper = mount(component, { props: { label: 'Notify', description: 'By email.', error: 'Required.' } })
    const control = wrapper.get(tag)
    const ids = control.attributes('aria-describedby')?.split(' ') ?? []
    expect(ids).toHaveLength(2)
    const texts = ids.map((id) => wrapper.find(`[id="${id}"]`).text())
    expect(texts).toEqual(['Required.', 'By email.'])
    expect(control.attributes('aria-invalid')).toBe('true')
  })

  it('has no description or invalid state of its own by default', () => {
    const control = mount(component, { props: { label: 'Notify' } }).get(tag)
    expect(control.attributes('aria-describedby')).toBeUndefined()
    expect(control.attributes('aria-invalid')).toBeUndefined()
  })

  it('keeps the label inside the label element and marks itself disabled', () => {
    const wrapper = mount(component, { props: { label: 'Notify', description: 'By email.', disabled: true } })
    expect(wrapper.get('label').text()).toBe('Notify')
    expect(wrapper.get(tag).attributes('disabled')).toBeDefined()
    expect(wrapper.classes()).toContain('u-toggle--disabled')
  })
})

describe('EmptyState', () => {
  it('uses a level 2 heading by default, and the level asked for', () => {
    expect(mount(EmptyState, { props: { title: 'None' } }).find('h2').exists()).toBe(true)
    expect(mount(EmptyState, { props: { title: 'None', headingLevel: 3 } }).find('h3').exists()).toBe(true)
  })

  it('is not a landmark and leaves out the action area without an action', () => {
    const empty = mount(EmptyState, { props: { title: 'None' } })
    expect(empty.attributes('aria-label')).toBeUndefined()
    expect(empty.find('.empty__action').exists()).toBe(false)
  })
})

describe('PageHeader', () => {
  it('leaves out the breadcrumb and action areas when they are not used', () => {
    const header = mount(PageHeader, { props: { title: 'Runs' } })
    expect(header.find('.page-header__crumbs').exists()).toBe(false)
    expect(header.find('.page-header__actions').exists()).toBe(false)
  })
})

describe('PropertyList', () => {
  it('shows a dash for an empty string but keeps a zero', () => {
    const list = mount(PropertyList, {
      props: { items: [{ key: 'a', label: 'A', value: '' }, { key: 'b', label: 'B', value: 0 }] },
    })
    expect(list.findAll('dd').map((value) => value.text())).toEqual(['-', '0'])
  })
})

describe('RunTimeline', () => {
  it('keeps the same cells in every row, so the columns line up', () => {
    const timeline = mount(RunTimeline, {
      props: { steps: [{ id: '1', name: 'A', state: 'done' }, { id: '2', name: 'B', state: 'done', attempts: 2 }] },
    })
    const counts = timeline.findAll('summary').map((row) => row.element.children.length)
    expect(counts).toEqual([5, 5])
  })

  it('shows a disclosure chevron, which display:grid would otherwise remove', () => {
    const timeline = mount(RunTimeline, { props: { steps: [{ id: '1', name: 'A', state: 'done' }] } })
    expect(timeline.find('summary svg.run-timeline__chevron').exists()).toBe(true)
  })

  it('colours a message as an error only on a failed step', () => {
    const timeline = mount(RunTimeline, {
      props: {
        steps: [
          { id: '1', name: 'A', state: 'skipped', message: 'Not needed' },
          { id: '2', name: 'B', state: 'failed', message: 'Broke' },
        ],
      },
    })
    const [skipped, failed] = timeline.findAll('.run-timeline__message')
    expect(skipped?.classes()).not.toContain('run-timeline__message--failed')
    expect(failed?.classes()).toContain('run-timeline__message--failed')
  })

  it('says so when an open step has nothing to show, unless the detail slot fills it', () => {
    const steps = [{ id: '1', name: 'A', state: 'done' }]
    expect(mount(RunTimeline, { props: { steps } }).text()).toContain('No details for this step.')
    const withSlot = mount(RunTimeline, { props: { steps }, slots: { detail: '<pre>log</pre>' } })
    expect(withSlot.text()).not.toContain('No details for this step.')
  })

  it('says so when there are no steps, and takes a list label', () => {
    const empty = mount(RunTimeline, { props: { steps: [] } })
    expect(empty.find('ol').exists()).toBe(false)
    expect(empty.text()).toBe('No steps yet.')
    const named = mount(RunTimeline, { props: { steps: [{ id: '1', name: 'A', state: 'done' }], label: 'Replay' } })
    expect(named.get('ol').attributes('aria-label')).toBe('Replay')
  })
})

describe('WorkTreeLogo', () => {
  it('scales the wordmark with the mark', () => {
    const size = (props: { size?: number }) => mount(WorkTreeLogo, { props }).get<HTMLElement>('.logo__word').element.style.fontSize
    expect(size({})).toBe('16px')
    expect(size({ size: 20 })).toBe('12px')
  })
})

describe('DesignView', () => {
  it('renders every section and every status, on our own controls only', async () => {
    const view = mount(DesignView, { global: { plugins: [createPinia()] } })
    await flushPromises()
    const titles = view.findAll('section.block h2').map((heading) => heading.text())
    expect(titles).toEqual(
      expect.arrayContaining(['Buttons', 'Text fields', 'Table and pagination', 'Load states', 'Board', 'Dialogs']),
    )
    const shown = view.findAll('[data-status]').map((badge) => badge.attributes('data-status'))
    for (const status of STATUS_NAMES) expect(shown).toContain(status)
    expect(view.html()).not.toContain('<fluent-')
  })
})
