// The four plant drawings (docs/04 3.3): petal, flower, seed and bud. Every plant in the product (the
// logo, workflow avatars, area bands, canvas nodes) is drawn from these, so they share one hand.
// Each returns SVG path data in its own unit space, centred on the origin; callers scale with a
// viewBox or a transform. Pure functions: no DOM, no Vue.

/** Round to two decimals and print without a float tail or a negative zero. */
export function num(value: number): string {
  const rounded = Math.round(value * 100) / 100
  return String(rounded === 0 ? 0 : rounded)
}

export interface PetalOptions {
  /** From where the petal starts to its tip. */
  length: number
  /** How far each side bulges out from the centre line. */
  width: number
  /** Distance from the origin to the base of the petal. 0 makes petals meet at the centre. */
  start?: number
  /** Round petals belong to app steps and the logo; pointed ones are a proposal (docs/04 15, item 2). */
  shape?: 'round' | 'pointed'
  /** Where along the length the two control points sit, as fractions. Defaults to 0.3 and 0.75. */
  ratios?: readonly [near: number, far: number]
}

/** One petal pointing straight up (towards negative y) from the origin. */
export function petal({ length, width, start = 0, shape = 'round', ratios = [0.3, 0.75] }: PetalOptions): string {
  const [near, far] = ratios
  const base = -start
  const y1 = -(start + near * length)
  const y2 = -(start + far * length)
  const tip = -(start + length)
  // A pointed petal pulls its far control point in towards the centre line, so the tip narrows.
  const x2 = shape === 'pointed' ? width * 0.35 : width
  return (
    `M0 ${num(base)}` +
    `C${num(width)} ${num(y1)} ${num(x2)} ${num(y2)} 0 ${num(tip)}` +
    `C${num(-x2)} ${num(y2)} ${num(-width)} ${num(y1)} 0 ${num(base)}Z`
  )
}

export interface FlowerOptions extends PetalOptions {
  /** How many petals, evenly turned. The first points straight up. */
  petals: number
}

export interface FlowerDrawing {
  /** The path of one petal; draw it once per angle. */
  petal: string
  /** Clockwise turns in degrees, one per petal, starting at 0 (straight up). */
  angles: number[]
}

/** A flower: the same petal turned evenly around the origin. */
export function flower({ petals, ...petalOptions }: FlowerOptions): FlowerDrawing {
  const count = Math.max(1, Math.round(petals))
  const step = 360 / count
  return {
    petal: petal(petalOptions),
    angles: Array.from({ length: count }, (_, index) => Math.round(index * step * 100) / 100),
  }
}

export interface SeedDrawing {
  /** The teardrop, its point along positive x (the direction of the flow). */
  body: string
  /** A light eye in the round end. */
  eye: { cx: number; cy: number; r: number }
}

/** A seed: a teardrop pointing along the flow, with a light eye. `size` is its length. */
export function seed(size: number): SeedDrawing {
  const half = size / 2
  const height = size * 0.36
  const body =
    `M${num(half)} 0` +
    `C0 ${num(-height * 0.9)} ${num(-half)} ${num(-height)} ${num(-half)} 0` +
    `C${num(-half)} ${num(height)} 0 ${num(height * 0.9)} ${num(half)} 0Z`
  return { body, eye: { cx: Math.round(-size * 18) / 100, cy: 0, r: Math.round(size * 9) / 100 } }
}

/** A closed bud: an upright drop, its point at the top. `size` is its height. */
export function bud(size: number): string {
  const half = size / 2
  const width = size * 0.42
  return (
    `M0 ${num(-half)}` +
    `C${num(width)} ${num(-size * 0.2)} ${num(width)} ${num(size * 0.35)} 0 ${num(half)}` +
    `C${num(-width)} ${num(size * 0.35)} ${num(-width)} ${num(-size * 0.2)} 0 ${num(-half)}Z`
  )
}
