<script setup lang="ts">
// Title, optional subtitle, a breadcrumb slot above and an actions slot on the right.
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="page-header">
    <div class="page-header__crumbs"><slot name="breadcrumbs" /></div>
    <div class="page-header__row">
      <div class="page-header__titles">
        <h1 class="page-header__title">{{ title }}</h1>
        <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
      </div>
      <div class="page-header__actions"><slot name="actions" /></div>
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: grid;
  gap: var(--spacingVerticalXS);
  padding-bottom: var(--uaf-gap);
  border-bottom: var(--strokeWidthThin) solid var(--uaf-border);
}
.page-header__crumbs:empty {
  display: none;
}
.page-header__row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--spacingHorizontalL);
}
.page-header__title {
  font-size: var(--fontSizeBase600);
  line-height: var(--lineHeightBase600);
}
.page-header__subtitle {
  margin: 0;
  color: var(--uaf-text-muted);
}
.page-header__actions {
  display: flex;
  align-items: center;
  gap: var(--spacingHorizontalS);
}
</style>
