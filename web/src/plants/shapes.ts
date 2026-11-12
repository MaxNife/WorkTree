// The plant drawings (docs/04 3.3): petal, flower, round flower, seed and bud. Every plant in the product (the
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

export interface RoundFlowerOptions {
  /** How many round petals, evenly spaced. The first sits straight up. */
  petals: number
  /** The flower's radius: petals reach about this far from the centre. */
  radius: number
}

export interface RoundFlowerDrawing {
  /** One circle per petal, centred on the origin's ring. */
  petals: { cx: number; cy: number; r: number }[]
  /** The solid body that joins the petals. */
  body: number
  /** The light core in the middle. */
  core: number
}

/**
 * The solid, scalloped flower approved on the mockup sheet (docs/mockups/redesign-options.html):
 * round petals on a ring at 0.58 of the radius, each 0.44 of it, joined by a body of 0.62 with a
 * light core of 0.26. Workflow avatars and app steps on the canvas are this flower.
 */
export function roundFlower({ petals, radius }: RoundFlowerOptions): RoundFlowerDrawing {
  const count = Math.max(1, Math.round(petals))
  const ring = radius * 0.58
  const size = Math.round(radius * 44) / 100
  return {
    petals: Array.from({ length: count }, (_, index) => {
      const angle = (index * 2 * Math.PI) / count - Math.PI / 2
      return { cx: Number(num(Math.cos(angle) * ring)), cy: Number(num(Math.sin(angle) * ring)), r: size }
    }),
    body: Math.round(radius * 62) / 100,
    core: Math.round(radius * 26) / 100,
  }
}

export interface SeedDrawing {
  /** The teardrop: a round end on the left and its point along positive x (the flow). */
  body: string
  /** A light eye in the round end. */
  eye: { cx: number; cy: number; r: number }
}

/** A seed, `size` long from the round end to the point (the mockup's seed is 42 long). */
export function seed(size: number): SeedDrawing {
  const k = size / 42
  const body =
    `M${num(-20 * k)} 0` +
    `C${num(-20 * k)} ${num(-15 * k)} ${num(-6 * k)} ${num(-22 * k)} ${num(22 * k)} 0` +
    `C${num(-6 * k)} ${num(22 * k)} ${num(-20 * k)} ${num(15 * k)} ${num(-20 * k)} 0Z`
  return { body, eye: { cx: Number(num(-6 * k)), cy: 0, r: Number(num(5 * k)) } }
}

/** A closed bud, `size` tall, its point at the top (the mockup's bud is 42 tall). */
export function bud(size: number): string {
  const k = size / 42
  return (
    `M0 ${num(-22 * k)}` +
    `C${num(14 * k)} ${num(-8 * k)} ${num(14 * k)} ${num(10 * k)} 0 ${num(20 * k)}` +
    `C${num(-14 * k)} ${num(10 * k)} ${num(-14 * k)} ${num(-8 * k)} 0 ${num(-22 * k)}Z`
  )
}
