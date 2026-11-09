// Activity family colours: the one place WorkTree uses vivid colour (docs/design-language.md,
// "Canvas"). They paint the core of a node on the Studio canvas and the dot beside a family name.
// The rest of the app stays on the neutral, warm palette in tokens.ts.
import type { IconName } from '@/icons/paths'

export type Family =
  | 'trigger'
  | 'files'
  | 'documents'
  | 'matching'
  | 'network'
  | 'messages'
  | 'human'
  | 'alerts'
  | 'logic'

export interface FamilyStyle {
  label: string
  /** Fill of the node core. */
  color: string
  /** The icon on the core: white, or near-black where white would not reach 3:1. */
  ink: string
  icon: IconName
}

export const FAMILIES: Record<Family, FamilyStyle> = {
  trigger: { label: 'Triggers', color: '#D9381E', ink: '#ffffff', icon: 'trigger' },
  files: { label: 'Files and transfer', color: '#1A6FC4', ink: '#ffffff', icon: 'folder' },
  documents: { label: 'Documents', color: '#5B45D6', ink: '#ffffff', icon: 'document-text' },
  matching: { label: 'Matching', color: '#C81D72', ink: '#ffffff', icon: 'compare' },
  network: { label: 'Network', color: '#0A7F96', ink: '#ffffff', icon: 'globe' },
  messages: { label: 'Messages', color: '#0C8564', ink: '#ffffff', icon: 'mail' },
  human: { label: 'Human tasks', color: '#F4A80D', ink: '#231F2E', icon: 'person' },
  alerts: { label: 'Alerts', color: '#A81E2B', ink: '#ffffff', icon: 'bell' },
  logic: { label: 'Logic', color: '#2B2638', ink: '#ffffff', icon: 'branch' },
}

export const FAMILY_NAMES = Object.keys(FAMILIES) as Family[]
