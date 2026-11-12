import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AreaBand from '@/components/AreaBand.vue'
import LeafMark from '@/components/LeafMark.vue'
import WorkflowFlower from '@/components/WorkflowFlower.vue'
import { currentNavId, pathMatches } from '@/components/shell/navMatch'
import { flowerFor } from '@/plants'
import { AREA_COLOURS, areaColour, colourVars, neighbour } from '@/theme/areas'

describe('currentNavId', () => {
  const entries = [
    { id: 'operations', to: '/operations', depth: 0 },
    { id: 'operations.dashboard', to: '/operations', depth: 1 },
    { id: 'operations.runs', to: '/operations/runs', depth: 1 },
    { id: 'studio', to: '/studio', depth: 0 },
  ]

  it('prefers the deeper entry when a parent and child share a link', () => {
    expect(currentNavId(entries, '/operations')).toBe('operations.dashboard')
  })

  it('takes the longest link that the path lies under', () => {
    expect(currentNavId(entries, '/operations/runs/abc')).toBe('operations.runs')
    expect(currentNavId(entries, '/studio/workflows/w1')).toBe('studio')
  })

  it('falls back to the area row when its children are not shown', () => {
    expect(currentNavId(entries.filter((entry) => entry.depth === 0), '/operations/runs')).toBe('operations')
  })

  it('matches nothing for a path outside every entry, and never a prefix of a word', () => {
    expect(currentNavId(entries, '/settings')).toBeUndefined()
    expect(pathMatches('/operations', '/operationsx')).toBe(false)
    expect(pathMatches('/', '/anything')).toBe(true)
  })
})

describe('area colours', () => {
  it('gives each of the eight areas its colour from the guide', () => {
    expect(AREA_COLOURS).toEqual({
      home: 'marigold',
      operations: 'hibiscus',
      inbox: 'orchid',
      studio: 'iris',
      data: 'lagoon',
      connections: 'morning-glory',
      insights: 'fern',
      admin: 'night-soil',
    })
    expect(areaColour('operations.runs')).toBeUndefined()
    expect(areaColour('toString')).toBeUndefined()
  })

  it('maps Night soil to ink and the page tint, and finds a neighbour for every colour', () => {
    expect(colourVars('night-soil')).toEqual({ strong: 'var(--wt-ink)', soft: 'var(--wt-sunken)', deep: 'var(--wt-ink)' })
    expect(colourVars('fern').soft).toBe('var(--wt-fern-soft)')
    expect(neighbour('hibiscus')).toBe('marigold')
    expect(neighbour('orchid')).toBe('hibiscus')
    expect(neighbour('night-soil')).toBe('iris')
  })
})

describe('LeafMark', () => {
  it('is a decorative leaf in the colour it is given', () => {
    const leaf = mount(LeafMark, { props: { colour: 'lagoon', size: 14 } })
    expect(leaf.attributes('aria-hidden')).toBe('true')
    expect(leaf.attributes('style')).toContain('--leaf-fill: var(--wt-lagoon)')
    expect(leaf.attributes('style')).toContain('width: 14px')
  })
})

describe('WorkflowFlower', () => {
  it('draws the flower derived from the workflow id', () => {
    const { flower, petals } = flowerFor('wf-42')
    const svg = mount(WorkflowFlower, { props: { id: 'wf-42' } })
    expect(svg.attributes('aria-hidden')).toBe('true')
    expect(svg.attributes('data-flower')).toBe(flower)
    // One circle per petal, plus the body that joins them.
    expect(svg.findAll('.workflow-flower__bloom circle')).toHaveLength(petals + 1)
  })

  it('takes an explicit colour and petal count, kept within five to nine', () => {
    const svg = mount(WorkflowFlower, { props: { id: 'wf-42', flower: 'orchid', petals: 12 } })
    expect(svg.attributes('data-flower')).toBe('orchid')
    expect(svg.findAll('.workflow-flower__bloom circle')).toHaveLength(10)
  })
})

describe('AreaBand', () => {
  it('shows the title, summary and action on the area tint, with decorative flowers', () => {
    const band = mount(AreaBand, {
      props: { colour: 'hibiscus', title: 'Operations', summary: '3 runs growing', size: 'tall' },
      slots: { action: '<button>Run now</button>' },
    })
    expect(band.get('h1').text()).toBe('Operations')
    expect(band.text()).toContain('3 runs growing')
    expect(band.get('.band__action').text()).toBe('Run now')
    expect(band.attributes('style')).toContain('--band-fill: var(--wt-hibiscus-soft)')
    expect(band.get('.band__garden').attributes('aria-hidden')).toBe('true')
    expect(band.findAll('.band__garden svg')).toHaveLength(2)
  })

  it('marks prod with a Night soil pill and a line along the bottom; other environments stay quiet', () => {
    const prod = mount(AreaBand, { props: { colour: 'iris', title: 'Studio', environment: 'prod' } })
    expect(prod.classes()).toContain('band--prod')
    expect(prod.get('.band__env').classes()).toContain('band__env--prod')
    const dev = mount(AreaBand, { props: { colour: 'iris', title: 'Studio', environment: 'dev' } })
    expect(dev.classes()).not.toContain('band--prod')
    expect(dev.get('.band__env').classes()).not.toContain('band__env--prod')
    expect(mount(AreaBand, { props: { colour: 'iris', title: 'Studio' } }).find('.band__env').exists()).toBe(false)
  })
})
