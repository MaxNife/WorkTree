import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import NodeCard from '@/components/NodeCard.vue'
import { ACTIVITY_LOOKS, activityLook, APPS, NODE_KINDS } from '@/theme/apps'

// Every activity the backend registers, read from its source so a new one cannot slip in unmapped.
// Files starting with an underscore are helpers and the template for writing a new activity.
const ACTIVITIES_DIR = resolve(__dirname, '..', '..', 'activities')
const backendActivities = readdirSync(ACTIVITIES_DIR)
  .filter((file) => file.endsWith('.py') && !file.startsWith('_'))
  .flatMap((file) => [...readFileSync(join(ACTIVITIES_DIR, file), 'utf8').matchAll(/^ {4}name = "([a-z0-9_]+)"/gm)])
  .map((match) => match[1] ?? '')

describe('activity looks', () => {
  it('reads the 27 activities the backend registers', () => {
    expect(backendActivities).toHaveLength(27)
  })

  it('maps every backend activity to a node, and nothing else', () => {
    expect(Object.keys(ACTIVITY_LOOKS).sort()).toEqual([...backendActivities].sort())
    for (const name of backendActivities) expect(NODE_KINDS).toContain(activityLook(name).kind)
  })

  it('follows docs/07 9.1 for the apps, skills and tools', () => {
    expect(activityLook('excel')).toMatchObject({ kind: 'app', label: 'Spreadsheet', colour: 'fern' })
    expect(activityLook('oracle_bulk_load')).toMatchObject({ kind: 'app', label: 'Database', colour: 'morning-glory' })
    expect(activityLook('run_python')).toMatchObject({ kind: 'app', label: 'Code', colour: 'night-soil' })
    expect(activityLook('matching')).toMatchObject({ kind: 'skill', label: 'Match' })
    expect(activityLook('human_task')).toMatchObject({ kind: 'person', colour: 'marigold' })
    expect(activityLook('sleep').kind).toBe('wait')
    expect(activityLook('fail')).toMatchObject({ kind: 'stop', colour: 'hibiscus' })
  })

  it('draws an unknown activity as a Night soil app under its own name', () => {
    expect(activityLook('quantum_ledger')).toEqual({ kind: 'app', label: 'quantum_ledger', colour: 'night-soil', icon: 'workflow' })
    expect(activityLook('toString').label).toBe('toString')
  })

  it('gives each app the colour docs/07 5 sets', () => {
    expect(Object.fromEntries(Object.entries(APPS).map(([key, app]) => [key, app.colour]))).toEqual({
      spreadsheet: 'fern',
      pdf: 'hibiscus',
      database: 'morning-glory',
      files: 'marigold',
      archive: 'marigold',
      email: 'orchid',
      web: 'lagoon',
      sftp: 'lagoon',
      browser: 'iris',
      word: 'morning-glory',
      text: 'fern',
      code: 'night-soil',
      ai: 'iris',
    })
  })
})

describe('NodeCard', () => {
  it('shows the title, the app or skill name, the run status and its output ports', () => {
    const card = mount(NodeCard, { props: { title: 'Match ledger', activity: 'matching', status: 'done', durationMs: 900 } })
    expect(card.attributes('aria-label')).toBe('Match ledger, Match')
    expect(card.text()).toContain('Done')
    expect(card.text()).toContain('900 ms')
    expect(card.findAll('.node__port').map((port) => port.attributes('title'))).toEqual(['done', 'failed'])
  })

  it('draws the shape of its kind in its colour, never through an undefined variable', () => {
    const shapes = {
      excel: '.node__body',
      matching: 'path.node__petal',
      human_task: 'circle.node__eye',
      sleep: '.node__bud',
      echo: '.node__rib',
      fail: '.node__stem',
    }
    for (const [activity, selector] of Object.entries(shapes)) {
      const card = mount(NodeCard, { props: { title: 'A', activity } })
      expect(card.attributes('data-kind'), activity).toBe(activityLook(activity).kind)
      expect(card.find(selector).exists(), activity).toBe(true)
    }
    const code = mount(NodeCard, { props: { title: 'Run script', activity: 'run_python' } })
    expect(code.attributes('style')).toContain('--c-strong: var(--wt-ink)')
    expect(code.attributes('style')).not.toContain('night-soil')
  })

  it('draws eight petals on an app and one petal per route on a router, each in its route colour', () => {
    expect(mount(NodeCard, { props: { title: 'A', activity: 'sftp' } }).findAll('.node__petal')).toHaveLength(8)
    const router = mount(NodeCard, {
      props: { title: 'Any unmatched?', look: { kind: 'router', colour: 'night-soil' }, routes: ['fern', 'marigold', 'orchid'] },
    })
    const petals = router.findAll('.node__petal')
    expect(petals).toHaveLength(3)
    expect(petals.map((petal) => petal.attributes('style'))).toEqual([
      expect.stringContaining('--c-strong: var(--wt-fern)'),
      expect.stringContaining('--c-strong: var(--wt-marigold)'),
      expect.stringContaining('--c-strong: var(--wt-orchid)'),
    ])
    // Each petal keeps its own turn as an attribute; CSS never sets a transform on a petal.
    expect(petals.map((petal) => petal.attributes('transform'))).toEqual(['rotate(0)', 'rotate(120)', 'rotate(240)'])
  })

  it('maps run status to the plant state', () => {
    const states = { pending: 'pending', running: 'running', done: 'done', failed: 'failed', suspended: 'waiting', cancelled: 'pending' }
    for (const [status, state] of Object.entries(states)) {
      expect(mount(NodeCard, { props: { title: 'A', activity: 'csv', status } }).attributes('data-state'), status).toBe(state)
    }
    expect(mount(NodeCard, { props: { title: 'A', activity: 'csv' } }).attributes('data-state')).toBe('idle')
  })

  it('fills petals to the progress while running, or half of them and loops without one', () => {
    const lit = (props: Record<string, unknown>) =>
      mount(NodeCard, { props: { title: 'A', activity: 'csv', ...props } }).findAll('.node__fill .node__petal--lit').length
    expect(lit({})).toBe(8)
    expect(lit({ status: 'running', progress: 0.25 })).toBe(2)
    expect(lit({ status: 'running', progress: 1.5 })).toBe(8)
    expect(lit({ status: 'running' })).toBe(4)
    expect(lit({ status: 'pending' })).toBe(0)
    const looping = mount(NodeCard, { props: { title: 'A', activity: 'csv', status: 'running' } })
    expect(looping.findAll('.node__fill .node__petal--loop')).toHaveLength(8)
    // Pale petals sit inside one outline: an edge layer behind the fill, only while something is pale.
    expect(looping.find('.node__edge').exists()).toBe(true)
    expect(mount(NodeCard, { props: { title: 'A', activity: 'csv', status: 'done' } }).find('.node__edge').exists()).toBe(false)
    const measured = mount(NodeCard, { props: { title: 'A', activity: 'csv', status: 'running', progress: 0.5 } })
    expect(measured.find('.node__petal--loop').exists()).toBe(false)
  })

  it('wilts and wears a dot when failed; shows a halo while waiting and a ring when selected', () => {
    const failed = mount(NodeCard, { props: { title: 'A', activity: 'pdf', status: 'failed' } })
    expect(failed.find('.node__alert').exists()).toBe(true)
    expect(failed.find('g[transform*="rotate(16)"]').exists()).toBe(true)
    expect(mount(NodeCard, { props: { title: 'A', activity: 'pdf', status: 'waiting' } }).find('.node__halo').exists()).toBe(true)
    const selected = mount(NodeCard, { props: { title: 'A', activity: 'pdf', selected: true } })
    expect(selected.classes()).toContain('node--selected')
    expect(selected.find('.node__ring').exists()).toBe(true)
  })

  it('gives Finish and Stop no ports, and names a node without a label cleanly', () => {
    expect(mount(NodeCard, { props: { title: 'Stop', activity: 'fail' } }).find('.node__ports').exists()).toBe(false)
    expect(mount(NodeCard, { props: { title: 'End', look: { kind: 'finish' } } }).find('.node__ports').exists()).toBe(false)
    expect(mount(NodeCard, { props: { title: 'Ask', activity: 'human_task', ports: ['approve', 'reject'] } }).findAll('.node__port')).toHaveLength(2)
    expect(mount(NodeCard, { props: { title: 'End', look: { kind: 'finish' } } }).attributes('aria-label')).toBe('End')
  })

  it('says in its name when it needs setup or has a problem, not only in its drawing', () => {
    const card = mount(NodeCard, { props: { title: 'Read rows', activity: 'excel', incomplete: true, problem: true } })
    expect(card.attributes('aria-label')).toBe('Read rows, Spreadsheet, needs setup, has a problem')
    expect(card.classes()).toContain('node--pale')
    expect(card.find('.node__alert').exists()).toBe(true)
  })

  it('opens when its run finishes on screen, but not when it is first drawn done', async () => {
    const already = mount(NodeCard, { props: { title: 'A', activity: 'csv', status: 'done' } })
    expect(already.classes()).not.toContain('node--opening')
    const live = mount(NodeCard, { props: { title: 'A', activity: 'csv', status: 'running' } })
    await live.setProps({ status: 'done' })
    expect(live.classes()).toContain('node--opening')
  })
})
