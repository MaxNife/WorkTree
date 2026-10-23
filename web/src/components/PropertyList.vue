<script setup lang="ts">
// A label/value list for detail pages (the Linear-style properties column). Each value can be
// replaced with a slot named after the item key.
export interface PropertyItem {
  key: string
  label: string
  value?: string | number | null
}
defineProps<{ items: PropertyItem[] }>()
</script>

<template>
  <dl class="property-list">
    <div v-for="item in items" :key="item.key" class="property-list__row">
      <dt>{{ item.label }}</dt>
      <dd>
        <slot :name="item.key" :item="item">{{ item.value ?? '-' }}</slot>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.property-list {
  display: grid;
  gap: var(--spacingVerticalXS);
  margin: 0;
}
.property-list__row {
  display: grid;
  grid-template-columns: minmax(96px, 36%) 1fr;
  align-items: center;
  min-height: var(--uaf-control-height);
  gap: var(--spacingHorizontalS);
}
dt {
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
