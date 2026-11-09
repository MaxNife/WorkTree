<script setup lang="ts">
// Plain text only: no illustration or icon. Say what is missing and, if possible, how to fix it.
withDefaults(defineProps<{ title: string; description?: string; headingLevel?: 2 | 3 | 4 }>(), { headingLevel: 2 })
</script>

<template>
  <section class="empty">
    <component :is="`h${headingLevel}`" class="empty__title">{{ title }}</component>
    <p v-if="description" class="empty__text">{{ description }}</p>
    <div v-if="$slots.default" class="empty__action"><slot /></div>
  </section>
</template>

<style scoped>
.empty {
  display: grid;
  gap: var(--space-4);
  max-width: 52ch;
  padding: var(--space-24) 0;
}
.empty__title {
  margin: 0;
  font-size: var(--font-size-16);
  font-weight: var(--weight-semibold);
  line-height: var(--line-height-22);
}
.empty__text {
  margin: 0;
  color: var(--uaf-text-muted);
}
.empty__action {
  margin-top: var(--space-8);
}
</style>
