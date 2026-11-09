import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EmptyState from '@/components/EmptyState.vue'
import NodeCard from '@/components/NodeCard.vue'
import PageHeader from '@/components/PageHeader.vue'
import PropertyList from '@/components/PropertyList.vue'
import RunTimeline from '@/components/RunTimeline.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import UButton from '@/components/UButton.vue'
import UCheckbox from '@/components/UCheckbox.vue'
import UIcon from '@/components/UIcon.vue'
import USwitch from '@/components/USwitch.vue'
import UTextInput from '@/components/UTextInput.vue'
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
import { ICONS } from '@/icons/paths'
import { formatDuration, statusStyle } from '@/status'

describe('status helpers', () => {
  it('maps backend statuses to a kind, icon and label', () => {
    expect(statusStyle('failed')).toMatchObject({ kind: 'danger', label: 'Failed' })
    expect(statusStyle('suspended')).toMatchObject({ kind: 'warn' })
    expect(statusStyle('mystery')).toMatchObject({ kind: 'neutral', label: 'mystery' })
  })

  it('formats durations', () => {
    expect(formatDuration(850)).toBe('850 ms')
    expect(formatDuration(4200)).toBe('4.2 s')
    expect(formatDuration(185_000)).toBe('3 m 05 s')
    expect(formatDuration(3_720_000)).toBe('1 h 02 m')
    expect(formatDuration(null)).toBe('-')
    expect(formatDuration(-1)).toBe('-')
  })
})

describe('UIcon', () => {
  it('is hidden from assistive tech unless labelled', () => {
    const decorative = mount(UIcon, { props: { name: 'check' } })
    expect(decorative.attributes('aria-hidden')).toBe('true')
    expect(decorative.attributes('role')).toBeUndefined()
    const labelled = mount(UIcon, { props: { name: 'check', label: 'Passed' } })
    expect(labelled.attributes('role')).toBe('img')
    expect(labelled.attributes('aria-label')).toBe('Passed')
  })

  it('has a drawing for every icon name', () => {
    for (const name of Object.keys(ICONS)) {
      expect(mount(UIcon, { props: { name: name as keyof typeof ICONS } }).find('path, circle, rect').exists()).toBe(true)
    }
  })
})

describe('StatusBadge', () => {
  it('is a dot plus its word, never a pill or an icon', () => {
    const badge = mount(StatusBadge, { props: { status: 'failed' } })
    expect(badge.text()).toBe('Failed')
    expect(badge.find('.status__dot').exists()).toBe(true)
    expect(badge.find('svg').exists()).toBe(false)
    expect(badge.classes()).toContain('status--danger')
  })

  it('accepts a custom label', () => {
    expect(mount(StatusBadge, { props: { status: 'open', label: '3 open' } }).text()).toBe('3 open')
  })
})

describe('WorkTreeLogo', () => {
  it('is named WorkTree for assistive tech and shows the two-tone wordmark', () => {
    const logo = mount(WorkTreeLogo)
    expect(logo.attributes('aria-label')).toBe('WorkTree')
    expect(logo.get('.logo__work').text()).toBe('Work')
    expect(logo.get('.logo__tree').text()).toBe('Tree')
    expect(logo.find('svg').exists()).toBe(true)
  })

  it('can show the sprout mark alone', () => {
    const logo = mount(WorkTreeLogo, { props: { markOnly: true } })
    expect(logo.find('.logo__word').exists()).toBe(false)
    expect(logo.find('svg').exists()).toBe(true)
  })
})

describe('PageHeader, PropertyList and EmptyState', () => {
  it('renders the title, subtitle and actions', () => {
    const header = mount(PageHeader, {
      props: { title: 'Runs', subtitle: 'Last 24 hours' },
      slots: { actions: '<button>Run now</button>' },
    })
    expect(header.get('h1').text()).toBe('Runs')
    expect(header.text()).toContain('Last 24 hours')
    expect(header.find('button').text()).toBe('Run now')
  })

  it('renders properties, with a dash for missing values and slot overrides', () => {
    const list = mount(PropertyList, {
      props: { items: [{ key: 'a', label: 'Owner', value: 'Ops' }, { key: 'b', label: 'Env' }, { key: 'c', label: 'State' }] },
      slots: { c: '<em>custom</em>' },
    })
    const text = list.text()
    expect(text).toContain('Owner')
    expect(text).toContain('Ops')
    expect(list.findAll('dd')[1]?.text()).toBe('-')
    expect(list.findAll('dd')[2]?.html()).toContain('<em>custom</em>')
  })

  it('renders an empty state with an action slot', () => {
    const empty = mount(EmptyState, { props: { title: 'No runs' }, slots: { default: '<a href="#">Create</a>' } })
    expect(empty.get('h2').text()).toBe('No runs')
    expect(empty.find('a').exists()).toBe(true)
  })
})

describe('RunTimeline', () => {
  const steps = [
    { id: '1', name: 'Fetch', state: 'done', durationMs: 1200 },
    { id: '2', name: 'Match', state: 'failed', durationMs: 5000, attempts: 3, message: 'Tolerance exceeded' },
  ]

  it('lists steps with state and duration, and opens failed steps by default', () => {
    const timeline = mount(RunTimeline, { props: { steps } })
    const items = timeline.findAll('li')
    expect(items).toHaveLength(2)
    expect(items[0]?.text()).toContain('1.2 s')
    expect(items[0]?.find('details').attributes('open')).toBeUndefined()
    expect(items[1]?.find('details').attributes('open')).toBeDefined()
    expect(items[1]?.text()).toContain('attempt 3')
    expect(items[1]?.text()).toContain('Tolerance exceeded')
  })

  it('renders the per-step detail slot', () => {
    const timeline = mount(RunTimeline, {
      props: { steps },
      slots: { detail: '<template #detail="{ step }"><pre>log for {{ step.name }}</pre></template>' },
    })
    expect(timeline.text()).toContain('log for Fetch')
  })
})

describe('NodeCard', () => {
  it('shows the title, activity, run status and both output ports', () => {
    const card = mount(NodeCard, { props: { title: 'Match ledger', activity: 'matching', status: 'done', durationMs: 900 } })
    expect(card.attributes('aria-label')).toBe('Match ledger, matching')
    expect(card.text()).toContain('Done')
    expect(card.text()).toContain('900 ms')
    expect(card.text()).toContain('done')
    expect(card.text()).toContain('failed')
  })

  it('marks the selected node', () => {
    expect(mount(NodeCard, { props: { title: 'A', activity: 'x', selected: true } }).classes()).toContain('node--selected')
  })
})

describe('base controls', () => {
  it('UButton passes appearance and emits click', async () => {
    const button = mount(UButton, { props: { appearance: 'primary', icon: 'play' }, slots: { default: 'Run' } })
    const element = button.get('button')
    expect(element.classes()).toContain('u-button--primary')
    await element.trigger('click')
    expect(button.emitted('click')).toHaveLength(1)
    expect(button.find('svg').exists()).toBe(true)
  })

  it('UButton marks itself disabled', () => {
    expect(mount(UButton, { props: { disabled: true } }).get('button').attributes('disabled')).toBeDefined()
  })

  it('UTextInput updates its model from the input event', async () => {
    const input = mount(UTextInput, { props: { label: 'Name', modelValue: '', 'onUpdate:modelValue': () => undefined } })
    const element = input.get('input')
    ;(element.element as HTMLInputElement).value = 'hello'
    await element.trigger('input')
    expect(input.emitted('update:modelValue')?.[0]).toEqual(['hello'])
    expect(input.text()).toContain('Name')
  })

  it('UCheckbox and USwitch update their model from the change event', async () => {
    const box = mount(UCheckbox, { props: { label: 'Notify', modelValue: false } })
    ;(box.get('input').element as HTMLInputElement).checked = true
    await box.get('input').trigger('change')
    expect(box.emitted('update:modelValue')?.[0]).toEqual([true])

    const toggle = mount(USwitch, { props: { label: 'Enabled', modelValue: true } })
    expect(toggle.get('input').attributes('role')).toBe('switch')
    ;(toggle.get('input').element as HTMLInputElement).checked = false
    await toggle.get('input').trigger('change')
    expect(toggle.emitted('update:modelValue')?.[0]).toEqual([false])
  })
})
