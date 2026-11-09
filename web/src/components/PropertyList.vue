<script setup lang="ts">
// A label/value list for detail pages (the Linear-style properties column). Each value can be
// replaced with a slot named after the item key.
export interface PropertyItem {
  key: string
  label: string
  value?: string | number | null
}
defineProps<{ items: PropertyItem[] }>()

const shown = (value: PropertyItem['value']): string | number => (value === '' ? '-' : (value ?? '-'))
</script>

<template>
  <dl class="property-list">
    <div v-for="item in items" :key="item.key" class="property-list__row">
      <dt>{{ item.label }}</dt>
      <dd>
        <slot :name="item.key" :item="item">{{ shown(item.value) }}</slot>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.property-list {
  display: grid;
  gap: var(--space-4);
  margin: 0;
}
/* Baseline, not centre: a value that wraps keeps its first line level with the label. */
.property-list__row {
  display: grid;
  grid-template-columns: minmax(96px, 36%) minmax(0, 1fr);
  align-items: baseline;
  gap: var(--space-8);
}
dt,
dd {
  padding-block: var(--space-4);
  overflow-wrap: anywhere;
}
dt {
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
  line-height: var(--line-height-16);
}
dd {
  margin: 0;
}
</style>
