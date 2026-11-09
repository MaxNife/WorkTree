<script setup lang="ts">
import UIcon from '@/components/UIcon.vue'
import { useBreadcrumbs } from './breadcrumbs'

const crumbs = useBreadcrumbs()
</script>

<template>
  <nav v-if="crumbs.length" class="crumbs" aria-label="Breadcrumb">
    <ol class="crumbs__list">
      <li v-for="(crumb, index) in crumbs" :key="index" class="crumbs__item">
        <UIcon v-if="index > 0" name="chevron-right" :size="12" class="crumbs__sep" />
        <RouterLink v-if="crumb.to" :to="crumb.to" class="crumbs__link">{{ crumb.label }}</RouterLink>
        <span v-else class="crumbs__current" aria-current="page">{{ crumb.label }}</span>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.crumbs {
  min-width: 0;
}
.crumbs__list {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: hidden;
  white-space: nowrap;
}
.crumbs__item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  min-width: 0;
}
.crumbs__sep {
  color: var(--uaf-text-muted);
}
.crumbs__link {
  color: var(--uaf-text-muted);
  text-decoration: none;
  border-radius: var(--uaf-radius);
}
.crumbs__link:hover {
  color: var(--uaf-text);
  text-decoration: underline;
}
.crumbs__current {
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: var(--weight-semibold);
}
</style>
