// A workflow's flower: one of the seven colours and five to nine petals (docs/04 3.1). Until the
// backend stores a chosen flower (docs/04 15, item 3), it is derived from the workflow id, so the
// same workflow always looks the same in every list, run and chart.
import { FLOWER_NAMES, type FlowerName } from '@/theme/tokens'

export const MIN_PETALS = 5
export const MAX_PETALS = 9

export interface FlowerIdentity {
  flower: FlowerName
  petals: number
}

/** FNV-1a, 32 bit: small, fast and well spread for short ids. */
function hash(text: string): number {
  let value = 0x811c9dc5
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index)
    value = Math.imul(value, 0x01000193)
  }
  return value >>> 0
}

/** The flower for a workflow id. Colour and petal count come from different bits of the hash. */
export function flowerFor(id: string): FlowerIdentity {
  const value = hash(id)
  const flower = FLOWER_NAMES[value % FLOWER_NAMES.length] ?? 'iris'
  const petals = MIN_PETALS + ((value >>> 16) % (MAX_PETALS - MIN_PETALS + 1))
  return { flower, petals }
}

/** Keep a stored or requested petal count inside the allowed range. */
export function clampPetals(petals: number): number {
  return Math.min(MAX_PETALS, Math.max(MIN_PETALS, Math.round(petals)))
}
