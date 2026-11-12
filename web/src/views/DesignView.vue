<script setup lang="ts">
// The living reference of the design language: every token group and shared component in every
// state, in whichever theme and density is active. Use the two selects here to review all of them.
import { ref } from 'vue'
import BoardView from '@/components/BoardView.vue'
import CodeBlock from '@/components/CodeBlock.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import EmptyState from '@/components/EmptyState.vue'
import FilterBar from '@/components/FilterBar.vue'
import LoadState from '@/components/LoadState.vue'
import NodeCard from '@/components/NodeCard.vue'
import PageHeader from '@/components/PageHeader.vue'
import PropertyList from '@/components/PropertyList.vue'
import RelativeTime from '@/components/RelativeTime.vue'
import RunTimeline, { type TimelineStep } from '@/components/RunTimeline.vue'
import AreaBand from '@/components/AreaBand.vue'
import LeafMark from '@/components/LeafMark.vue'
import AppPage from '@/components/shell/AppPage.vue'
import MessageBar from '@/components/shell/MessageBar.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import UButton from '@/components/UButton.vue'
import UCheckbox from '@/components/UCheckbox.vue'
import UDialog from '@/components/UDialog.vue'
import UIcon from '@/components/UIcon.vue'
import UPagination from '@/components/UPagination.vue'
import USelect from '@/components/USelect.vue'
import USwitch from '@/components/USwitch.vue'
import UTabs from '@/components/UTabs.vue'
import UTextArea from '@/components/UTextArea.vue'
import UTextInput from '@/components/UTextInput.vue'
import WorkflowFlower from '@/components/WorkflowFlower.vue'
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
import { ICONS, type IconName } from '@/icons/paths'
import { STATUS_NAMES } from '@/status'
import { usePreferences } from '@/stores/preferences'
import { DENSITIES, THEME_MODES, type Density, type ThemeMode } from '@/theme/apply'
import { AREA_COLOURS, type AreaName } from '@/theme/areas'
import { APPS, FLOW_LOOKS } from '@/theme/apps'
import { THEME_LABELS } from '@/theme/tokens'

const LONG_TEXT =
  'Reconcile the month-end statement against the general ledger for every subsidiary, including the ones that report late'
const UNBROKEN_TEXT = 'statement-2026-10-31-subsidiary-northern-region-final-reviewed-approved-v12.csv'

const preferences = usePreferences()
const modeOptions = THEME_MODES.map((mode) => ({
  value: mode,
  label: mode === 'system' ? 'System' : THEME_LABELS[mode],
}))
const densityOptions = DENSITIES.map((density) => ({
  value: density,
  label: density === 'compact' ? 'Compact' : 'Comfortable',
}))

const sections = [
  ['d-colour', 'Colour'],
  ['d-type', 'Type, spacing and radius'],
  ['d-logo', 'Logo'],
  ['d-garden', 'Leaves, flowers and bands'],
  ['d-icons', 'Icons'],
  ['d-canvas', 'Canvas nodes'],
  ['d-status', 'Status'],
  ['d-buttons', 'Buttons'],
  ['d-fields', 'Text fields'],
  ['d-choices', 'Choices'],
  ['d-filter', 'Filter bar'],
  ['d-tabs', 'Tabs'],
  ['d-header', 'Page header'],
  ['d-table', 'Table and pagination'],
  ['d-states', 'Load states'],
  ['d-messages', 'Messages'],
  ['d-detail', 'Property list and empty state'],
  ['d-timeline', 'Run timeline'],
  ['d-board', 'Board'],
  ['d-code', 'Code and time'],
  ['d-dialogs', 'Dialogs'],
] as const

const AREA_LABELS: Record<AreaName, string> = {
  home: 'Home',
  operations: 'Operations',
  inbox: 'Inbox',
  studio: 'Studio',
  data: 'Data',
  connections: 'Connections',
  insights: 'Insights',
  admin: 'Admin',
}
const openDemo = ref('running')
const FLOWER_SAMPLES = ['Bank reconciliation', 'Vendor onboarding', 'Month-end close', 'Payroll check', 'Expense audit']

const principles: { icon: IconName; title: string; text: string }[] = [
  { icon: 'leaf', title: 'A garden on a clean ground', text: 'Seven flower colours on a light, faintly violet base. Tables, forms and long text stay white and exact.' },
  { icon: 'plant', title: 'Colour means something', text: 'Every area has its colour and every workflow its flower. Iris marks the main action, Night soil the strongest.' },
  { icon: 'tree', title: 'Every state in words', text: 'A dot always comes with its word, every control has a visible focus ring, and contrast passes in all themes.' },
]

const appearances = ['primary', 'strong', 'destructive', 'secondary', 'outline', 'subtle'] as const
const colourGroups: { title: string; tokens: [string, string][] }[] = [
  {
    title: 'Surfaces',
    tokens: [
      ['--wt-ground', 'Page'],
      ['--wt-surface', 'Surface'],
      ['--wt-sunken', 'Sunken'],
      ['--wt-surface-hover', 'Hover'],
      ['--wt-surface-selected', 'Selected'],
      ['--wt-line', 'Border'],
      ['--wt-line-strong', 'Strong border'],
      ['--wt-border-control', 'Control edge'],
    ],
  },
  {
    title: 'Text',
    tokens: [
      ['--wt-ink', 'Text'],
      ['--wt-text-secondary', 'Secondary'],
      ['--wt-muted', 'Muted'],
      ['--wt-text-disabled', 'Disabled'],
      ['--wt-link', 'Link'],
      ['--wt-focus', 'Focus ring'],
    ],
  },
  {
    title: 'Accent',
    tokens: [
      ['--wt-accent', 'Accent fill'],
      ['--wt-accent-hover', 'Accent hover'],
      ['--wt-accent-tint', 'Accent tint'],
      ['--wt-accent-text', 'Accent mark'],
    ],
  },
  {
    title: 'Status',
    tokens: [
      ['--wt-ok', 'Done'],
      ['--wt-warn', 'Waiting'],
      ['--wt-attention', 'Attention'],
      ['--wt-danger', 'Failed'],
    ],
  },
]
const typeScale = [
  ['12', '16', 'Secondary text and labels'],
  ['14', '20', 'Body text and controls'],
  ['16', '22', 'Empty state title'],
  ['20', '28', 'Section title'],
  ['24', '32', 'Page title'],
] as const
const spacing = ['2', '4', '6', '8', '10', '12', '16', '20', '24', '32']
const radii = [
  ['--wt-radius', 'Controls, 8px'],
  ['--wt-radius-container', 'Containers, 12px'],
] as const
const icons = Object.keys(ICONS) as IconName[]
const iconWeight = ref<'regular' | 'fill'>('regular')
const iconTabs = [
  { id: 'regular', label: 'Regular' },
  { id: 'fill', label: 'Fill' },
]


const text = ref('')
const filled = ref('Month-end close')
const secret = ref('masked value')
const notes = ref('')
const choice = ref('finance')
const choices = [
  { value: 'finance', label: 'Finance operations' },
  { value: 'treasury', label: 'Treasury' },
  { value: 'audit', label: 'Internal audit' },
]
const on = ref(true)
const off = ref(false)

const search = ref('')
const owner = ref('')
const filtersActive = ref(true)

const tab = ref('runs')
const tabs = [
  { id: 'runs', label: 'Runs', count: 128 },
  { id: 'tasks', label: 'Tasks', count: 4 },
  { id: 'history', label: 'History' },
]

interface RunRow {
  id: string
  name: string
  status: string
  owner: string | null
  duration: string
}
const columns: DataTableColumn[] = [
  { key: 'name', label: 'Workflow', sortable: true },
  { key: 'status', label: 'Status', sortable: true, width: '140px' },
  { key: 'owner', label: 'Owner' },
  { key: 'duration', label: 'Duration', align: 'end', width: '96px' },
]
const rows: RunRow[] = [
  { id: 'r1', name: 'Month-end close', status: 'running', owner: 'Finance operations', duration: '3 m 05 s' },
  { id: 'r2', name: 'Vendor onboarding', status: 'failed', owner: 'Procurement', duration: '850 ms' },
  { id: 'r3', name: LONG_TEXT, status: 'done', owner: null, duration: '1 h 02 m' },
]
const sort = ref('-name')
const selectedRun = ref('r2')
const offset = ref(25)

const boardColumns = [
  { id: 'open', title: 'Open', items: [{ id: 'b1', name: 'Approve journal' }, { id: 'b2', name: LONG_TEXT }] },
  { id: 'claimed', title: 'Claimed', items: [{ id: 'b3', name: 'Match statement' }] },
  { id: 'completed', title: 'Completed', items: [] },
]

const logText = '2026-11-05 09:14:02 fetch statement\n2026-11-05 09:14:04 matched 412 of 416 rows'
const minutesAgo = (minutes: number): string => new Date(Date.now() - minutes * 60_000).toISOString()

const steps: TimelineStep[] = [
  { id: '1', name: 'Fetch statement', state: 'done', durationMs: 1840 },
  { id: '2', name: 'Match to ledger', state: 'failed', durationMs: 92_000, attempts: 3, message: 'Amount tolerance exceeded for 4 rows' },
  { id: '3', name: 'Wait for approval', state: 'waiting', durationMs: 3_720_000, message: 'Held for the finance reviewer' },
  { id: '4', name: LONG_TEXT, state: 'dispatched', durationMs: 850 },
  { id: '5', name: 'Post journal', state: 'pending' },
]
const properties = [
  { key: 'owner', label: 'Owner', value: 'Finance operations' },
  { key: 'env', label: 'Environment', value: 'test' },
  { key: 'status', label: 'Status' },
  { key: 'attempts', label: 'Attempts', value: 0 },
  { key: 'reviewer', label: 'Reviewer', value: null },
  { key: 'file', label: 'Source file', value: UNBROKEN_TEXT },
  { key: 'purpose', label: 'A label long enough that it has to wrap', value: LONG_TEXT },
]

const dialogOpen = ref(false)
const confirmOpen = ref(false)
const rejectOpen = ref(false)
</script>

<template>
  <AppPage title="Design language" subtitle="Tokens and shared components. Decisions are recorded in docs/04-ui-reimplementation-guide.md.">
    <template #actions>
      <USelect
        class="switcher"
        label="Theme"
        :options="modeOptions"
        :model-value="preferences.mode"
        @update:model-value="preferences.setMode($event as ThemeMode)"
      />
      <USelect
        class="switcher"
        label="Density"
        :options="densityOptions"
        :model-value="preferences.density"
        @update:model-value="preferences.setDensity($event as Density)"
      />
    </template>

    <div class="design">
      <nav class="design__nav" aria-label="Design language sections">
        <a v-for="[id, title] in sections" :key="id" :href="`#${id}`" class="design__nav-link">{{ title }}</a>
      </nav>

      <div class="design__content">
        <section class="intro" aria-label="Principles">
          <WorkTreeLogo :size="28" />
          <ul class="principles">
            <li v-for="principle in principles" :key="principle.title" class="principle">
              <UIcon class="principle__icon" :name="principle.icon" :size="22" weight="fill" />
              <div>
                <h3 class="principle__title">{{ principle.title }}</h3>
                <p class="principle__text">{{ principle.text }}</p>
              </div>
            </li>
          </ul>
        </section>

        <section id="d-colour" class="block" aria-labelledby="d-colour-title">
          <h2 id="d-colour-title">Colour</h2>
          <div v-for="group in colourGroups" :key="group.title" class="colour-group">
            <h3 class="spec">{{ group.title }}</h3>
            <ul class="swatches">
              <li v-for="[token, name] in group.tokens" :key="token" class="swatch-card">
                <span class="swatch" :style="{ background: `var(${token})` }" />
                <span class="swatch-card__name">{{ name }}</span>
                <code>{{ token }}</code>
              </li>
            </ul>
          </div>
        </section>

        <section id="d-type" class="block" aria-labelledby="d-type-title">
          <h2 id="d-type-title">Type, spacing and radius</h2>
          <p
            v-for="[size, line, use] in typeScale"
            :key="size"
            class="type-sample"
            :style="{ fontSize: `var(--font-size-${size})`, lineHeight: `var(--line-height-${line})` }"
          >
            {{ use }} <code>{{ size }}/{{ line }}</code>
          </p>
          <div class="row row--end">
            <div v-for="step in spacing" :key="step" class="spacing">
              <span class="spacing__bar" :style="{ width: `var(--space-${step})` }" />
              <code>{{ step }}</code>
            </div>
          </div>
          <div class="row">
            <span v-for="[token, use] in radii" :key="token" class="radius" :style="{ borderRadius: `var(${token})` }">
              {{ use }}
            </span>
            <span class="radius radius--float">Floating panel shadow</span>
          </div>
        </section>

        <section id="d-logo" class="block" aria-labelledby="d-logo-title">
          <h2 id="d-logo-title">Logo</h2>
          <div class="row"><WorkTreeLogo :size="28" /><WorkTreeLogo :size="20" /><WorkTreeLogo mark-only :size="20" /></div>
        </section>

        <section id="d-garden" class="block" aria-labelledby="d-garden-title">
          <h2 id="d-garden-title">Leaves, flowers and bands</h2>
          <p class="note">Each area has a leaf in its colour. Each workflow has a flower: a colour and five to nine petals.</p>
          <ul class="areas">
            <li v-for="(colour, area) in AREA_COLOURS" :key="area">
              <LeafMark :colour="colour" :size="14" />{{ AREA_LABELS[area] }}
            </li>
          </ul>
          <div class="row">
            <span v-for="id in FLOWER_SAMPLES" :key="id" class="flower-sample">
              <WorkflowFlower :id="id" :size="24" />{{ id }}
            </span>
          </div>
          <div class="row">
            <WorkflowFlower v-for="petals in [5, 6, 7, 8, 9]" :key="petals" flower="iris" :petals="petals" :size="32" />
          </div>
          <AreaBand colour="hibiscus" title="Operations" summary="4 runs growing, 1 failed in the last hour." size="tall">
            <template #action><UButton appearance="strong" icon="play">Run now</UButton></template>
          </AreaBand>
          <AreaBand colour="iris" title="Invoice reconciliation" summary="Version 12, published 3 days ago." environment="prod" />
          <AreaBand colour="night-soil" title="Admin" summary="12 people, 3 roles." environment="dev" />
        </section>

        <section id="d-icons" class="block" aria-labelledby="d-icons-title">
          <h2 id="d-icons-title">Icons</h2>
          <p class="note">Phosphor Icons. Regular in the interface; fill on coloured shapes and in tight spaces.</p>
          <UTabs v-model="iconWeight" :tabs="iconTabs" label="Icon weight" />
          <ul class="icons">
            <li v-for="icon in icons" :key="icon">
              <UIcon :name="icon" :size="20" :weight="iconWeight" /><span>{{ icon }}</span>
            </li>
          </ul>
        </section>

        <section id="d-canvas" class="block" aria-labelledby="d-canvas-title">
          <h2 id="d-canvas-title">Canvas nodes</h2>
          <p class="note">
            Solid plants. Shape says what a node does; colour says which app it belongs to. Pointed petals for skills are
            still a proposal.
          </p>
          <h3 class="sub">Kinds</h3>
          <div class="canvas">
            <NodeCard title="Every weekday" :look="FLOW_LOOKS.schedule" summary="06:00" />
            <NodeCard title="Download statement" activity="sftp" summary="Supplier share" />
            <NodeCard title="Match to ledger" activity="matching" summary="One to one, 0.01 tolerance" />
            <NodeCard title="Review unmatched" activity="human_task" summary="Operators, 4 h" />
            <NodeCard title="Any unmatched?" :look="FLOW_LOOKS.router" summary="2 routes" :routes="['fern', 'marigold']" :ports="['yes', 'no']" />
            <NodeCard title="Wait for the bank" activity="sleep" summary="Until 07:00" />
            <NodeCard title="Set period" activity="echo" summary="period_end" />
            <NodeCard title="Month-end close" :look="FLOW_LOOKS.subworkflow" summary="Version 4" />
            <NodeCard title="Finish" :look="FLOW_LOOKS.finish" summary="Done" />
            <NodeCard title="Stop" activity="fail" summary="With failure" />
          </div>
          <h3 class="sub">States</h3>
          <div class="canvas">
            <NodeCard title="Read rows" activity="excel" summary="Invoices sheet" />
            <NodeCard title="Read rows" activity="excel" status="pending" />
            <NodeCard title="Read rows" activity="excel" status="running" />
            <NodeCard title="Read rows" activity="excel" status="running" :progress="0.25" summary="1,204 of 4,800 rows" />
            <NodeCard title="Read rows" activity="excel" status="done" :duration-ms="4200" />
            <NodeCard title="Read rows" activity="excel" status="failed" :duration-ms="420" />
            <NodeCard title="Read rows" activity="excel" status="waiting" />
            <NodeCard title="Read rows" activity="excel" selected />
            <NodeCard title="Read rows" activity="excel" incomplete summary="Needs a file" />
            <NodeCard title="Read rows" activity="excel" problem summary="Sheet is missing" />
          </div>
          <div class="row">
            <NodeCard title="Query ledger" activity="gl_query" :status="openDemo" />
            <UButton @click="openDemo = openDemo === 'done' ? 'running' : 'done'">
              {{ openDemo === 'done' ? 'Run again' : 'Finish the run' }}
            </UButton>
          </div>
          <h3 class="sub">Apps</h3>
          <ul class="apps">
            <li v-for="(app, key) in APPS" :key="key"><LeafMark :colour="app.colour" :size="12" />{{ app.label }}</li>
          </ul>
        </section>

        <section id="d-status" class="block" aria-labelledby="d-status-title">
          <h2 id="d-status-title">Status</h2>
          <div class="row">
            <StatusBadge v-for="status in STATUS_NAMES" :key="status" :status="status" />
          </div>
          <div class="row">
            <StatusBadge status="needs_review" />
            <StatusBadge status="open" label="3 open" />
          </div>
        </section>

        <section id="d-buttons" class="block" aria-labelledby="d-buttons-title">
          <h2 id="d-buttons-title">Buttons</h2>
          <div v-for="appearance in appearances" :key="appearance" class="row">
            <span class="spec">{{ appearance }}</span>
            <UButton :appearance="appearance">Button</UButton>
            <UButton :appearance="appearance" icon="play">With icon</UButton>
            <UButton :appearance="appearance" icon="edit" label="Edit" />
            <UButton :appearance="appearance" disabled>Disabled</UButton>
            <UButton :appearance="appearance" icon="edit" label="Edit, disabled" disabled />
            <UButton :appearance="appearance" loading>Saving</UButton>
          </div>
        </section>

        <section id="d-fields" class="block" aria-labelledby="d-fields-title">
          <h2 id="d-fields-title">Text fields</h2>
          <div class="fields">
            <UTextInput v-model="text" label="Default" placeholder="Month-end close" />
            <UTextInput v-model="filled" label="Required" required description="Shown in the run history." />
            <UTextInput v-model="text" label="Invalid" error="Enter a name for this workflow." />
            <UTextInput v-model="text" label="Invalid with help" description="Letters and numbers only." error="Remove the slash." />
            <UTextInput v-model="filled" label="Disabled" disabled />
            <UTextInput v-model="filled" label="Read only" readonly />
            <UTextInput v-model="secret" label="Password" type="password" />
            <UTextInput v-model="text" label="Search" type="search" placeholder="Search runs" />
            <UTextInput :model-value="LONG_TEXT" :label="LONG_TEXT" :description="UNBROKEN_TEXT" :error="LONG_TEXT" />
            <UTextArea v-model="notes" label="Notes" placeholder="Add a note" />
            <UTextArea v-model="notes" label="Required, five rows" required :rows="5" />
            <UTextArea :model-value="LONG_TEXT" label="Disabled" disabled />
            <UTextArea v-model="notes" label="With help" description="Shown under the field." />
            <UTextArea v-model="notes" label="With an error" error="Inputs must be a JSON object." />
          </div>
        </section>

        <section id="d-choices" class="block" aria-labelledby="d-choices-title">
          <h2 id="d-choices-title">Choices</h2>
          <div class="fields">
            <USelect v-model="choice" label="Owner" :options="choices" />
            <USelect v-model="owner" label="With placeholder" :options="choices" placeholder="Any owner" />
            <USelect v-model="choice" label="Disabled" :options="choices" disabled />
            <USelect v-model="choice" label="With help" :options="choices" description="Shown under the field." />
            <USelect v-model="owner" label="With an error" :options="choices" placeholder="Any owner" error="Choose an owner." />
          </div>
          <div class="fields">
            <UCheckbox v-model="on" label="Checked" />
            <UCheckbox v-model="off" label="Unchecked" />
            <UCheckbox v-model="on" label="Checked, disabled" disabled />
            <UCheckbox v-model="off" label="Unchecked, disabled" disabled />
            <UCheckbox v-model="off" label="With help" description="Email the owner when a run fails." />
            <UCheckbox v-model="off" label="Invalid" error="Accept the terms to continue." />
            <USwitch v-model="on" label="On" />
            <USwitch v-model="off" label="Off" />
            <USwitch v-model="on" label="On, disabled" disabled />
            <USwitch v-model="off" label="Off, disabled" disabled />
            <USwitch v-model="on" label="With help" description="Runs start on schedule." />
            <USwitch v-model="off" :label="LONG_TEXT" error="Publish the workflow first." />
          </div>
        </section>

        <section id="d-filter" class="block" aria-labelledby="d-filter-title">
          <h2 id="d-filter-title">Filter bar</h2>
          <p class="note">Search, select and button sit on one line and share the control height of the density.</p>
          <FilterBar v-model:search="search" search-label="Search runs" :active="filtersActive" @clear="filtersActive = false">
            <USelect v-model="owner" label="Owner" :options="choices" placeholder="Any owner" />
            <UButton icon="filter">More filters</UButton>
          </FilterBar>
        </section>

        <section id="d-tabs" class="block" aria-labelledby="d-tabs-title">
          <h2 id="d-tabs-title">Tabs</h2>
          <UTabs v-model="tab" :tabs="tabs" label="Workflow sections" />
        </section>

        <section id="d-header" class="block" aria-labelledby="d-header-title">
          <h2 id="d-header-title">Page header</h2>
          <PageHeader :title="LONG_TEXT" :subtitle="UNBROKEN_TEXT">
            <template #actions>
              <UButton>Edit</UButton>
              <UButton appearance="primary" icon="play">Run now</UButton>
            </template>
          </PageHeader>
          <PageHeader title="Title only" />
        </section>

        <section id="d-table" class="block" aria-labelledby="d-table-title">
          <h2 id="d-table-title">Table and pagination</h2>
          <DataTable
            v-model:sort="sort"
            :columns="columns"
            :rows="rows"
            :row-key="(row) => row.id"
            :row-label="(row) => row.name"
            :selected-key="selectedRun"
            caption="Recent runs"
            @row-open="selectedRun = $event.id"
          >
            <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
          </DataTable>
          <UPagination v-model:offset="offset" :total="128" :limit="25" />
          <DataTable :columns="columns" :rows="rows.slice(0, 2)" :row-key="(row) => row.id" caption="Read-only runs">
            <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
          </DataTable>
        </section>

        <section id="d-states" class="block" aria-labelledby="d-states-title">
          <h2 id="d-states-title">Load states</h2>
          <p class="spec">Loading</p>
          <LoadState loading />
          <p class="spec">Error</p>
          <LoadState error="The runs could not be loaded." />
          <p class="spec">Empty</p>
          <LoadState empty empty-title="No runs yet" empty-description="Run the workflow to see its history here." />
          <p class="spec">Content</p>
          <LoadState>The list goes here.</LoadState>
        </section>

        <section id="d-messages" class="block" aria-labelledby="d-messages-title">
          <h2 id="d-messages-title">Messages</h2>
          <MessageBar>Scheduled maintenance starts at 18:00.</MessageBar>
          <MessageBar intent="success" title="Published">Version 12 is live.</MessageBar>
          <MessageBar intent="warning" dismissible>Two tasks are close to their deadline.</MessageBar>
          <MessageBar intent="error" title="Run failed">
            {{ LONG_TEXT }}
            <template #actions><UButton>Retry</UButton></template>
          </MessageBar>
        </section>

        <section id="d-detail" class="block" aria-labelledby="d-detail-title">
          <h2 id="d-detail-title">Property list and empty state</h2>
          <div class="split">
            <PropertyList :items="properties">
              <template #status><StatusBadge status="running" /></template>
            </PropertyList>
            <div>
              <EmptyState title="No runs yet" description="Run the workflow to see its history here." :heading-level="3" />
              <EmptyState title="No matching runs" description="Clear the filters to see every run." :heading-level="3">
                <UButton>Clear filters</UButton>
              </EmptyState>
            </div>
          </div>
        </section>

        <section id="d-timeline" class="block" aria-labelledby="d-timeline-title">
          <h2 id="d-timeline-title">Run timeline</h2>
          <RunTimeline :steps="steps" />
          <RunTimeline :steps="steps.slice(0, 2)" label="Run steps with logs">
            <template #detail="{ step }"><CodeBlock :text="logText" :label="`Log for ${step.name}`" /></template>
          </RunTimeline>
          <RunTimeline :steps="[]" />
        </section>

        <section id="d-board" class="block" aria-labelledby="d-board-title">
          <h2 id="d-board-title">Board</h2>
          <BoardView :columns="boardColumns" :item-key="(item) => item.id">
            <template #default="{ item }">{{ item.name }}</template>
          </BoardView>
        </section>

        <section id="d-code" class="block" aria-labelledby="d-code-title">
          <h2 id="d-code-title">Code and time</h2>
          <CodeBlock :text="logText" label="Run log" />
          <CodeBlock :text="`${LONG_TEXT} ${UNBROKEN_TEXT}`" label="Long line, scrolled" />
          <CodeBlock :text="`${LONG_TEXT} ${UNBROKEN_TEXT}`" label="Long line, wrapped" wrap />
          <div class="row">
            <RelativeTime :value="minutesAgo(0)" />
            <RelativeTime :value="minutesAgo(3)" />
            <RelativeTime :value="minutesAgo(180)" />
            <RelativeTime :value="minutesAgo(4320)" />
            <RelativeTime :value="minutesAgo(90 * 1440)" />
            <RelativeTime :value="null" />
          </div>
        </section>

        <section id="d-dialogs" class="block" aria-labelledby="d-dialogs-title">
          <h2 id="d-dialogs-title">Dialogs</h2>
          <div class="row">
            <UButton @click="dialogOpen = true">Open dialog</UButton>
            <UButton @click="confirmOpen = true">Open confirmation</UButton>
            <UButton @click="rejectOpen = true">Open required reason</UButton>
          </div>
          <UDialog v-model:open="dialogOpen" title="Rename workflow" persistent>
            <UTextInput v-model="filled" label="Name" required />
            <template #footer>
              <UButton @click="dialogOpen = false">Cancel</UButton>
              <UButton appearance="primary" @click="dialogOpen = false">Save</UButton>
            </template>
          </UDialog>
          <ConfirmDialog
            v-model:open="confirmOpen"
            title="Archive this workflow?"
            message="Its runs stay in the history."
            confirm-label="Archive"
            @confirm="confirmOpen = false"
          />
          <ConfirmDialog
            v-model:open="rejectOpen"
            title="Reject this task?"
            message="The requester sees your reason."
            confirm-label="Reject"
            reason-label="Reason"
            reason-required
            danger
            @confirm="rejectOpen = false"
          />
        </section>
      </div>
    </div>
  </AppPage>
</template>

<style scoped>
.design {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  align-items: start;
  gap: var(--space-24);
}
.design__nav {
  position: sticky;
  top: 0;
  display: grid;
  gap: var(--space-2);
  padding: var(--space-8);
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius-container);
  background: var(--wt-surface);
}
.design__nav-link {
  padding: var(--space-4) var(--space-8);
  border-radius: var(--wt-radius);
  color: var(--wt-text-secondary);
  font-size: var(--font-size-12);
  text-decoration: none;
}
.design__nav-link:hover {
  background: var(--wt-surface-hover);
  color: var(--wt-ink);
}
.design__content {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-16);
  min-width: 0;
}
.intro,
.block {
  display: grid;
  gap: var(--wt-gap);
  min-width: 0;
  padding: var(--space-20) var(--space-24);
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius-container);
  background: var(--wt-surface);
  scroll-margin-top: var(--space-16);
}
.intro {
  gap: var(--space-16);
  background: var(--wt-sunken);
}
.principles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-16);
  margin: 0;
  padding: 0;
  list-style: none;
}
.principle {
  display: flex;
  gap: var(--space-12);
}
.principle__icon {
  margin-top: 1px;
  color: var(--wt-accent-text);
}
.principle__title {
  font-size: var(--font-size-14);
}
.principle__text {
  margin: var(--space-2) 0 0;
  color: var(--wt-text-secondary);
  font-size: var(--font-size-12);
  line-height: var(--line-height-16);
}
.block > * {
  min-width: 0;
}
.block h2 {
  font-size: var(--font-size-20);
  line-height: var(--line-height-28);
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wt-gap);
}
.areas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8) var(--space-20);
  margin: 0;
  padding: 0;
  list-style: none;
}
.areas li,
.flower-sample {
  display: inline-flex;
  align-items: center;
  gap: var(--space-8);
}
.row--end {
  align-items: flex-end;
}
.spec {
  min-width: 10ch;
  margin: 0;
  color: var(--wt-muted);
  font-size: var(--font-size-12);
  font-weight: var(--weight-semibold);
}
.note,
.type-sample {
  margin: 0;
}
.note {
  color: var(--wt-muted);
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  align-items: start;
  gap: var(--space-12) var(--space-16);
}
.split {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-24);
}
.switcher {
  min-width: 160px;
}
.colour-group {
  display: grid;
  gap: var(--space-8);
}
.swatches,
.icons,
.apps {
  display: grid;
  gap: var(--wt-gap);
  margin: 0;
  padding: 0;
  list-style: none;
}
.swatches {
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
}
.swatch-card {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-8);
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius);
}
.swatch {
  height: 40px;
  margin-bottom: var(--space-4);
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: 6px;
}
.swatch-card__name {
  font-size: var(--font-size-12);
  font-weight: var(--weight-semibold);
}
.swatch-card code {
  overflow: hidden;
  color: var(--wt-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.icons {
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
}
.icons li,
.apps li {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-width: 0;
  color: var(--wt-text-secondary);
  font-size: var(--font-size-12);
}
.canvas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-24) var(--space-8);
  padding: var(--space-24) var(--space-16);
  border-radius: var(--wt-radius-container);
  background-color: var(--wt-ground);
  /* A soft dot grid (docs/04 10.3), faint in every theme so it never competes with labels. */
  background-image: radial-gradient(color-mix(in srgb, var(--wt-line-strong) 55%, transparent) 1px, transparent 1px);
  background-size: 18px 18px;
}
.apps {
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}
.sub {
  font-size: var(--font-size-16);
  line-height: var(--line-height-22);
}
code {
  font-family: var(--wt-font-mono);
  font-size: var(--font-size-12);
}
.spacing {
  display: grid;
  justify-items: start;
  gap: var(--space-4);
  min-width: 5ch;
  color: var(--wt-muted);
}
.spacing__bar {
  height: var(--space-8);
  border-radius: 2px;
  background: var(--wt-accent-text);
}
.radius {
  padding: var(--wt-cell-padding);
  border: var(--stroke-1) solid var(--wt-line-strong);
}
.radius--float {
  border-color: var(--wt-line);
  border-radius: var(--wt-radius-container);
  box-shadow: var(--wt-shadow-float);
}
@media (max-width: 900px) {
  .design {
    grid-template-columns: minmax(0, 1fr);
  }
  .design__nav {
    position: static;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  }
}
</style>
