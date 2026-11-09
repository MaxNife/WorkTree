<script setup lang="ts">
// Title, optional subtitle, a breadcrumb slot above and an actions slot on the right. A long title
// wraps, and the actions drop below it when the two no longer fit side by side.
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="page-header">
    <div v-if="$slots.breadcrumbs" class="page-header__crumbs"><slot name="breadcrumbs" /></div>
    <div class="page-header__row">
      <div class="page-header__titles">
        <h1 class="page-header__title">{{ title }}</h1>
        <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="page-header__actions"><slot name="actions" /></div>
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: grid;
  gap: var(--space-4);
  padding-bottom: var(--uaf-gap);
  border-bottom: var(--stroke-1) solid var(--uaf-border);
}
.page-header__row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-8) var(--space-16);
}
.page-header__titles {
  flex: 1 1 32ch;
  min-width: 0;
}
.page-header__title {
  font-size: var(--font-size-24);
  line-height: var(--line-height-32);
  overflow-wrap: anywhere;
}
.page-header__subtitle {
  margin: 0;
  max-width: 80ch;
  color: var(--uaf-text-muted);
  overflow-wrap: anywhere;
}
.page-header__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-8);
  max-width: 100%;
}
</style>
