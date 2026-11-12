// Each area's colour (docs/04 3.1): it paints the area's leaf in the sidebar, the band at the top of
// its pages and its empty states. Typed over all eight areas in the guide; the router has five so far.
import { FLOWER_NAMES, type FlowerName } from './tokens'

/** A flower, or Night soil (the ink colour), which only Admin uses. */
export type AreaColour = FlowerName | 'night-soil'

export const AREA_COLOURS = {
  home: 'marigold',
  operations: 'hibiscus',
  inbox: 'orchid',
  studio: 'iris',
  data: 'lagoon',
  connections: 'morning-glory',
  insights: 'fern',
  admin: 'night-soil',
} as const satisfies Record<string, AreaColour>

export type AreaName = keyof typeof AREA_COLOURS

/** The colour of an area by its id, or undefined for anything that is not an area. */
export function areaColour(id: string): AreaColour | undefined {
  return Object.hasOwn(AREA_COLOURS, id) ? AREA_COLOURS[id as AreaName] : undefined
}

/** CSS values for a colour: strong (marks), soft (fills) and deep (text on the soft fill). */
export function colourVars(colour: AreaColour): { strong: string; soft: string; deep: string } {
  if (colour === 'night-soil') return { strong: 'var(--wt-ink)', soft: 'var(--wt-sunken)', deep: 'var(--wt-ink)' }
  return { strong: `var(--wt-${colour})`, soft: `var(--wt-${colour}-soft)`, deep: `var(--wt-${colour}-deep)` }
}

/** The flower after this one in the palette order, for a second decoration beside the first. */
export function neighbour(colour: AreaColour): FlowerName {
  if (colour === 'night-soil') return 'iris'
  const index = FLOWER_NAMES.indexOf(colour)
  return FLOWER_NAMES[(index + 1) % FLOWER_NAMES.length] ?? 'iris'
}
