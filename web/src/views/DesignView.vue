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
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
import { ICONS, type IconName } from '@/icons/paths'
import { STATUS_NAMES } from '@/status'
import { usePreferences } from '@/stores/preferences'
import { DENSITIES, THEME_MODES, type Density, type ThemeMode } from '@/theme/apply'
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

const appearances = ['primary', 'secondary', 'outline', 'subtle'] as const
const colours = [
  '--uaf-surface',
  '--uaf-surface-sunken',
  '--uaf-surface-hover',
  '--uaf-surface-selected',
  '--uaf-text',
  '--uaf-text-muted',
  '--uaf-text-disabled',
  '--uaf-border',
  '--uaf-border-strong',
  '--uaf-accent',
  '--uaf-accent-text',
  '--uaf-link',
  '--uaf-focus',
  '--uaf-ok',
  '--uaf-warn',
  '--uaf-attention',
  '--uaf-danger',
]
const typeScale = [
  ['Base200', 'Secondary text and labels'],
  ['Base300', 'Body text and controls'],
  ['Base400', 'Empty state title'],
  ['Base500', 'Section title'],
  ['Base600', 'Page title'],
] as const
const spacing = ['XXS', 'XS', 'SNudge', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']
const radii = [
  ['--uaf-radius-container', 'Containers'],
  ['--uaf-radius', 'Controls'],
] as const
const icons = Object.keys(ICONS) as IconName[]

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
  <AppPage title="Design language" subtitle="Tokens and shared components. Decisions are recorded in docs/design-language.md.">
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

    <section class="block" aria-labelledby="d-colour">
      <h2 id="d-colour">Colour</h2>
      <ul class="swatches">
        <li v-for="colour in colours" :key="colour">
          <span class="swatch" :style="{ background: `var(${colour})` }" />
          <code>{{ colour }}</code>
        </li>
      </ul>
    </section>

    <section class="block" aria-labelledby="d-type">
      <h2 id="d-type">Type, spacing and radius</h2>
      <p
        v-for="[size, use] in typeScale"
        :key="size"
        class="type-sample"
        :style="{ fontSize: `var(--fontSize${size})`, lineHeight: `var(--lineHeight${size})` }"
      >
        {{ use }}
      </p>
      <div class="row row--end">
        <div v-for="step in spacing" :key="step" class="spacing">
          <span class="spacing__bar" :style="{ width: `var(--spacingHorizontal${step})` }" />
          <code>{{ step }}</code>
        </div>
      </div>
      <div class="row">
        <span v-for="[token, use] in radii" :key="token" class="radius" :style="{ borderRadius: `var(${token})` }">
          {{ use }}
        </span>
      </div>
    </section>

    <section class="block" aria-labelledby="d-logo">
      <h2 id="d-logo">Logo</h2>
      <div class="row"><WorkTreeLogo :size="28" /><WorkTreeLogo :size="20" /><WorkTreeLogo mark-only :size="20" /></div>
    </section>

    <section class="block" aria-labelledby="d-icons">
      <h2 id="d-icons">Icons (Fluent System Icons)</h2>
      <ul class="icons">
        <li v-for="icon in icons" :key="icon"><UIcon :name="icon" :size="20" /><span>{{ icon }}</span></li>
      </ul>
    </section>

    <section class="block" aria-labelledby="d-status">
      <h2 id="d-status">Status</h2>
      <div class="row">
        <StatusBadge v-for="status in STATUS_NAMES" :key="status" :status="status" />
      </div>
      <div class="row">
        <StatusBadge status="needs_review" />
        <StatusBadge status="open" label="3 open" />
      </div>
    </section>

    <section class="block" aria-labelledby="d-buttons">
      <h2 id="d-buttons">Buttons</h2>
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

    <section class="block" aria-labelledby="d-fields">
      <h2 id="d-fields">Text fields</h2>
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

    <section class="block" aria-labelledby="d-choices">
      <h2 id="d-choices">Choices</h2>
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

    <section class="block" aria-labelledby="d-filter">
      <h2 id="d-filter">Filter bar</h2>
      <p class="note">Search, select and button sit on one line and share the control height of the density.</p>
      <FilterBar v-model:search="search" search-label="Search runs" :active="filtersActive" @clear="filtersActive = false">
        <USelect v-model="owner" label="Owner" :options="choices" placeholder="Any owner" />
        <UButton icon="filter">More filters</UButton>
      </FilterBar>
    </section>

    <section class="block" aria-labelledby="d-tabs">
      <h2 id="d-tabs">Tabs</h2>
      <UTabs v-model="tab" :tabs="tabs" label="Workflow sections" />
    </section>

    <section class="block" aria-labelledby="d-header">
      <h2 id="d-header">Page header</h2>
      <PageHeader :title="LONG_TEXT" :subtitle="UNBROKEN_TEXT">
        <template #actions>
          <UButton>Edit</UButton>
          <UButton appearance="primary" icon="play">Run now</UButton>
        </template>
      </PageHeader>
      <PageHeader title="Title only" />
    </section>

    <section class="block" aria-labelledby="d-table">
      <h2 id="d-table">Table and pagination</h2>
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

    <section class="block" aria-labelledby="d-states">
      <h2 id="d-states">Load states</h2>
      <p class="spec">Loading</p>
      <LoadState loading />
      <p class="spec">Error</p>
      <LoadState error="The runs could not be loaded." />
      <p class="spec">Empty</p>
      <LoadState empty empty-title="No runs yet" empty-description="Run the workflow to see its history here." />
      <p class="spec">Content</p>
      <LoadState>The list goes here.</LoadState>
    </section>

    <section class="block" aria-labelledby="d-messages">
      <h2 id="d-messages">Messages</h2>
      <MessageBar>Scheduled maintenance starts at 18:00.</MessageBar>
      <MessageBar intent="success" title="Published">Version 12 is live.</MessageBar>
      <MessageBar intent="warning" dismissible>Two tasks are close to their deadline.</MessageBar>
      <MessageBar intent="error" title="Run failed">
        {{ LONG_TEXT }}
        <template #actions><UButton>Retry</UButton></template>
      </MessageBar>
    </section>

    <section class="block" aria-labelledby="d-detail">
      <h2 id="d-detail">Property list and empty state</h2>
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

    <section class="block" aria-labelledby="d-timeline">
      <h2 id="d-timeline">Run timeline</h2>
      <RunTimeline :steps="steps" />
      <RunTimeline :steps="steps.slice(0, 2)" label="Run steps with logs">
        <template #detail="{ step }"><CodeBlock :text="logText" :label="`Log for ${step.name}`" /></template>
      </RunTimeline>
      <RunTimeline :steps="[]" />
    </section>

    <section class="block" aria-labelledby="d-board">
      <h2 id="d-board">Board</h2>
      <BoardView :columns="boardColumns" :item-key="(item) => item.id">
        <template #default="{ item }">{{ item.name }}</template>
      </BoardView>
    </section>

    <section class="block" aria-labelledby="d-code">
      <h2 id="d-code">Code and time</h2>
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

    <section class="block" aria-labelledby="d-node">
      <h2 id="d-node">Node card</h2>
      <div class="row">
        <NodeCard title="Match ledger" activity="matching" status="done" :duration-ms="1840" />
        <NodeCard title="Post journal" activity="rest_call" status="failed" :duration-ms="420" selected />
      </div>
    </section>

    <section class="block" aria-labelledby="d-dialogs">
      <h2 id="d-dialogs">Dialogs</h2>
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
  </AppPage>
</template>

<style scoped>
.block {
  display: grid;
  gap: var(--uaf-gap);
  margin-top: var(--spacingVerticalXXL);
}
.block h2 {
  font-size: var(--fontSizeBase500);
  line-height: var(--lineHeightBase500);
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--uaf-gap);
}
.row--end {
  align-items: flex-end;
}
.spec {
  min-width: 10ch;
  margin: 0;
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
.note,
.type-sample {
  margin: 0;
}
.note {
  color: var(--uaf-text-muted);
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  align-items: start;
  gap: var(--spacingVerticalM) var(--spacingHorizontalL);
}
.split {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--spacingHorizontalXXL);
}
.switcher {
  min-width: 160px;
}
.swatches,
.icons {
  display: grid;
  gap: var(--uaf-gap);
  margin: 0;
  padding: 0;
  list-style: none;
}
.swatches {
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}
.icons {
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
}
.swatches li,
.icons li {
  display: flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  min-width: 0;
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
.swatch {
  flex: none;
  width: var(--spacingHorizontalXL);
  height: var(--spacingVerticalXL);
  border: var(--strokeWidthThin) solid var(--uaf-border-strong);
  border-radius: var(--uaf-radius-container);
}
code {
  font-family: var(--uaf-font-mono);
  font-size: var(--fontSizeBase200);
}
.spacing {
  display: grid;
  justify-items: start;
  gap: var(--spacingVerticalXS);
  min-width: 6ch;
  color: var(--uaf-text-muted);
}
.spacing__bar {
  height: var(--spacingVerticalS);
  background: var(--uaf-text-muted);
}
.radius {
  padding: var(--uaf-cell-padding);
  border: var(--strokeWidthThin) solid var(--uaf-border-strong);
}
</style>
