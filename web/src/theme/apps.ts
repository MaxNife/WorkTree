// What each node on the canvas looks like (docs/04 10.3, docs/07 2, 5 and 9.1). Shape says what a
// node does (its kind); colour says which app it belongs to. This replaces the nine activity
// families of the Rings and Bloom design. Today's activities map onto the apps of docs/07 9.1 until
// the connector framework replaces them.
import type { IconName } from '@/icons/paths'
import type { AreaColour } from './areas'

/**
 * trigger: a seed. app: a round-petal flower. skill: a pointed-petal dahlia. person: a sunflower.
 * router: an open bloom, one petal per route. wait: a closed bud. data: a small leaf (table and
 * value tools). finish: a leaf. stop: a wilted hibiscus. group: a cluster of blooms (sub-workflow).
 */
export type NodeKind = 'trigger' | 'app' | 'skill' | 'person' | 'router' | 'wait' | 'data' | 'finish' | 'stop' | 'group'

export const NODE_KINDS: readonly NodeKind[] = ['trigger', 'app', 'skill', 'person', 'router', 'wait', 'data', 'finish', 'stop', 'group']

export interface NodeLook {
  kind: NodeKind
  /** The app, skill or tool name shown under the node when it has no summary. */
  label: string
  colour: AreaColour
  icon: IconName
}

/** The built-in apps (docs/07 5) with their fixed colours. */
export const APPS = {
  spreadsheet: { label: 'Spreadsheet', colour: 'fern', icon: 'view-table' },
  pdf: { label: 'PDF', colour: 'hibiscus', icon: 'document' },
  database: { label: 'Database', colour: 'morning-glory', icon: 'database' },
  files: { label: 'Files', colour: 'marigold', icon: 'folder' },
  archive: { label: 'Archive', colour: 'marigold', icon: 'archive' },
  email: { label: 'Email', colour: 'orchid', icon: 'mail' },
  web: { label: 'Web request', colour: 'lagoon', icon: 'globe' },
  sftp: { label: 'SFTP', colour: 'lagoon', icon: 'server' },
  browser: { label: 'Browser', colour: 'iris', icon: 'open' },
  word: { label: 'Word', colour: 'morning-glory', icon: 'document-text' },
  text: { label: 'Text', colour: 'fern', icon: 'notes' },
  code: { label: 'Code', colour: 'night-soil', icon: 'code' },
  ai: { label: 'AI', colour: 'iris', icon: 'eye' },
} as const satisfies Record<string, Omit<NodeLook, 'kind'>>

export type AppKey = keyof typeof APPS

const app = (key: AppKey): NodeLook => ({ kind: 'app', ...APPS[key] })

/** Today's activity names (`uaf list-activities`) and how each one is drawn. */
export const ACTIVITY_LOOKS: Record<string, NodeLook> = {
  excel: app('spreadsheet'),
  csv: app('spreadsheet'),
  spreadsheet: app('spreadsheet'),
  pdf: app('pdf'),
  document: app('word'),
  gl_query: app('database'),
  oracle_query: app('database'),
  oracle_execute: app('database'),
  oracle_bulk_load: app('database'),
  http_request: app('web'),
  download_file: app('web'),
  sftp: app('sftp'),
  email: app('email'),
  graph_read_mail: app('email'),
  unc_archive: app('files'),
  zip: app('archive'),
  txt_log: app('text'),
  playwright_robot: app('browser'),
  playwright_script: app('browser'),
  ai_extract: app('ai'),
  run_python: app('code'),
  legacy_robot_wrapper: app('code'),
  // The guide sets no colour for skills; Match keeps Orchid, the old matching family colour.
  matching: { kind: 'skill', label: 'Match', colour: 'orchid', icon: 'compare' },
  human_task: { kind: 'person', label: 'Approval', colour: 'marigold', icon: 'person' },
  echo: { kind: 'data', label: 'Set values', colour: 'lagoon', icon: 'edit' },
  sleep: { kind: 'wait', label: 'Wait', colour: 'lagoon', icon: 'timer' },
  fail: { kind: 'stop', label: 'Stop', colour: 'hibiscus', icon: 'stop' },
}

/** Looks for nodes that are not activities: triggers, routers, finish and sub-workflows. */
export const FLOW_LOOKS = {
  schedule: { kind: 'trigger', label: 'Schedule', colour: 'hibiscus', icon: 'schedule' },
  webhook: { kind: 'trigger', label: 'Webhook', colour: 'hibiscus', icon: 'link' },
  router: { kind: 'router', label: 'If', colour: 'night-soil', icon: 'branch' },
  finish: { kind: 'finish', label: 'Finish', colour: 'fern', icon: 'check' },
  subworkflow: { kind: 'group', label: 'Sub-workflow', colour: 'iris', icon: 'workflow' },
} as const satisfies Record<string, NodeLook>

/** How an activity is drawn. An unknown one is a Night soil app node under its own name. */
export function activityLook(activity: string): NodeLook {
  return Object.hasOwn(ACTIVITY_LOOKS, activity)
    ? (ACTIVITY_LOOKS[activity] as NodeLook)
    : { kind: 'app', label: activity, colour: 'night-soil', icon: 'workflow' }
}
