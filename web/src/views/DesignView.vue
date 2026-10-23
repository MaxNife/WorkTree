<script setup lang="ts">
// A living reference of the design language: every token group and shared component, in whichever
// theme and density is active. Use the switches here to review all three themes.
import { ref } from 'vue'
import EmptyState from '@/components/EmptyState.vue'
import NodeCard from '@/components/NodeCard.vue'
import PageHeader from '@/components/PageHeader.vue'
import PropertyList from '@/components/PropertyList.vue'
import RunTimeline, { type TimelineStep } from '@/components/RunTimeline.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import UButton from '@/components/UButton.vue'
import UCheckbox from '@/components/UCheckbox.vue'
import UIcon from '@/components/UIcon.vue'
import USwitch from '@/components/USwitch.vue'
import UTextInput from '@/components/UTextInput.vue'
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
import { ICONS, type IconName } from '@/icons/paths'
import { usePreferences } from '@/stores/preferences'
import { THEME_LABELS, type ThemeName } from '@/theme/tokens'

const preferences = usePreferences()
const modes = ['system', 'light', 'dark', 'high-contrast'] as const
const modeLabel = (m: (typeof modes)[number]) => (m === 'system' ? 'System' : THEME_LABELS[m as ThemeName])
const icons = Object.keys(ICONS) as IconName[]
const statuses = ['pending', 'running', 'suspended', 'done', 'failed', 'cancelled', 'skipped', 'open']

const name = ref('')
const checked = ref(true)
const enabled = ref(false)

const steps: TimelineStep[] = [
  { id: '1', name: 'Fetch statement', state: 'done', durationMs: 1840 },
  { id: '2', name: 'Match to ledger', state: 'failed', durationMs: 92_000, attempts: 3, message: 'Amount tolerance exceeded for 4 rows' },
  { id: '3', name: 'Post journal', state: 'pending' },
]
const properties = [
  { key: 'owner', label: 'Owner', value: 'Finance operations' },
  { key: 'env', label: 'Environment', value: 'test' },
  { key: 'status', label: 'Status' },
]
</script>

<template>
  <PageHeader title="Design language" subtitle="Tokens and shared components. Decisions are recorded in docs/design-language.md.">
    <template #actions>
      <label class="switcher">
        Theme
        <select :value="preferences.mode" @change="preferences.setMode(($event.target as HTMLSelectElement).value as (typeof modes)[number])">
          <option v-for="m in modes" :key="m" :value="m">{{ modeLabel(m) }}</option>
        </select>
      </label>
      <label class="switcher">
        Density
        <select :value="preferences.density" @change="preferences.setDensity(($event.target as HTMLSelectElement).value as 'compact' | 'comfortable')">
          <option value="compact">Compact</option>
          <option value="comfortable">Comfortable</option>
        </select>
      </label>
    </template>
  </PageHeader>

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
    <div class="row"><StatusBadge v-for="s in statuses" :key="s" :status="s" /></div>
  </section>

  <section class="block" aria-labelledby="d-controls">
    <h2 id="d-controls">Controls</h2>
    <div class="row">
      <UButton appearance="primary" icon="play">Run now</UButton>
      <UButton>Secondary</UButton>
      <UButton appearance="outline" icon="retry">Retry</UButton>
      <UButton appearance="subtle">Subtle</UButton>
      <UButton disabled>Disabled</UButton>
    </div>
    <div class="row">
      <UTextInput v-model="name" label="Workflow name" placeholder="Month-end close" />
      <UCheckbox v-model="checked" label="Notify on failure" />
      <USwitch v-model="enabled" label="Enabled" />
    </div>
  </section>

  <section class="block" aria-labelledby="d-detail">
    <h2 id="d-detail">Property list and empty state</h2>
    <PropertyList :items="properties"><template #status><StatusBadge status="running" /></template></PropertyList>
    <EmptyState title="No runs yet" description="Run the workflow to see its history here." />
  </section>

  <section class="block" aria-labelledby="d-timeline">
    <h2 id="d-timeline">Run timeline</h2>
    <RunTimeline :steps="steps" />
  </section>

  <section class="block" aria-labelledby="d-node">
    <h2 id="d-node">Node card</h2>
    <div class="row">
      <NodeCard title="Match ledger" activity="matching" status="done" :duration-ms="1840" />
      <NodeCard title="Post journal" activity="rest_call" status="failed" :duration-ms="420" selected />
    </div>
  </section>
</template>

<style scoped>
.block {
  display: grid;
  gap: var(--uaf-gap);
  margin-top: var(--spacingVerticalXL);
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--uaf-gap);
}
.icons {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--uaf-gap);
  margin: 0;
  padding: 0;
  list-style: none;
}
.icons li {
  display: flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
.switcher {
  display: inline-flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
  color: var(--uaf-text-muted);
}
select {
  min-height: var(--uaf-control-height);
  padding: 0 var(--spacingHorizontalS);
  border: var(--strokeWidthThin) solid var(--uaf-border-strong);
  border-radius: var(--uaf-radius);
  background: var(--uaf-surface);
  color: var(--uaf-text);
  font: inherit;
}
</style>
