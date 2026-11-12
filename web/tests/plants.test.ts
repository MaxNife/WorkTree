import { describe, expect, it } from 'vitest'
import { bud, clampPetals, flower, flowerFor, MAX_PETALS, MIN_PETALS, num, petal, seed } from '@/plants'
import { FLOWER_NAMES } from '@/theme/tokens'

/** Every number in a path, in order. */
const numbers = (path: string): number[] => [...path.matchAll(/-?\d+(?:\.\d+)?/g)].map((match) => Number(match[0]))

describe('num', () => {
  it('prints at most two decimals, with no float tail and no negative zero', () => {
    expect(num(0.1 + 0.2)).toBe('0.3')
    expect(num(-0)).toBe('0')
    expect(num(-0.001)).toBe('0')
    expect(num(15.749999)).toBe('15.75')
  })
})

describe('petal', () => {
  // The logo's petals were drawn by hand first; the shared function must reproduce them exactly.
  it('draws the Bloom petal and its one-colour petal byte for byte', () => {
    expect(petal({ length: 21, width: 9.5 })).toBe('M0 0C9.5 -6.3 9.5 -15.75 0 -21C-9.5 -15.75 -9.5 -6.3 0 0Z')
    expect(petal({ length: 14, width: 6.5, start: 8, ratios: [0.25, 5 / 7] })).toBe(
      'M0 -8C6.5 -11.5 6.5 -18 0 -22C-6.5 -18 -6.5 -11.5 0 -8Z',
    )
  })

  it('is mirror-symmetric about the centre line and points up', () => {
    for (const shape of ['round', 'pointed'] as const) {
      const [x0, y0, ax, ay, bx, by, tx, ty, cx, cy, dx, dy, ex, ey] = numbers(petal({ length: 20, width: 8, start: 2, shape }))
      expect([x0, y0, tx, ty, ex, ey]).toEqual([0, -2, 0, -22, 0, -2])
      expect([cx, cy, dx, dy]).toEqual([-(bx ?? 0), by, -(ax ?? 0), ay])
    }
  })

  it('narrows towards the tip when pointed', () => {
    const round = numbers(petal({ length: 20, width: 8 }))
    const pointed = numbers(petal({ length: 20, width: 8, shape: 'pointed' }))
    expect(Math.abs(pointed[4] ?? 0)).toBeLessThan(Math.abs(round[4] ?? 0))
  })
})

describe('flower', () => {
  it.each([5, 6, 7, 8, 9])('turns %i petals evenly, the first straight up', (petals) => {
    const drawing = flower({ petals, length: 10, width: 4 })
    expect(drawing.angles).toHaveLength(petals)
    expect(drawing.angles[0]).toBe(0)
    const step = 360 / petals
    drawing.angles.forEach((angle, index) => expect(angle).toBeCloseTo(index * step, 1))
    expect(drawing.petal).toBe(petal({ length: 10, width: 4 }))
  })

  it('always draws at least one petal', () => {
    expect(flower({ petals: 0, length: 10, width: 4 }).angles).toEqual([0])
  })
})

describe('seed and bud', () => {
  it('draws a seed pointing along the flow, its eye in the round end', () => {
    const drawing = seed(20)
    const values = numbers(drawing.body)
    expect(values.every(Number.isFinite)).toBe(true)
    expect(Math.max(...values)).toBe(10)
    expect(drawing.eye.cx).toBeLessThan(0)
    expect(drawing.eye.r).toBeGreaterThan(0)
  })

  it('draws a bud upright, its point at the top', () => {
    const values = numbers(bud(20))
    expect(values.every(Number.isFinite)).toBe(true)
    expect(values.slice(0, 2)).toEqual([0, -10])
    expect(Math.max(...values)).toBe(10)
  })
})

describe('flowerFor', () => {
  const ids = Array.from({ length: 700 }, (_, index) => `wf-${index}`)

  it('gives the same workflow the same flower every time', () => {
    expect(flowerFor('invoice-reconciliation')).toEqual(flowerFor('invoice-reconciliation'))
  })

  it('uses every colour and every petal count from 5 to 9', () => {
    const results = ids.map(flowerFor)
    expect(new Set(results.map((result) => result.flower))).toEqual(new Set(FLOWER_NAMES))
    expect(new Set(results.map((result) => result.petals))).toEqual(new Set([5, 6, 7, 8, 9]))
  })

  // Colour and petal count come from different bits, so one colour does not fix the count.
  it('does not tie the petal count to the colour', () => {
    const counts = new Set(ids.map(flowerFor).filter((result) => result.flower === 'iris').map((result) => result.petals))
    expect(counts.size).toBeGreaterThan(2)
  })

  it('clamps petal counts into range', () => {
    expect(clampPetals(2)).toBe(MIN_PETALS)
    expect(clampPetals(40)).toBe(MAX_PETALS)
    expect(clampPetals(6.6)).toBe(7)
  })
})
