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
  gap: var(--spacingVerticalXS);
  max-width: 52ch;
  padding: var(--spacingVerticalXXL) 0;
}
.empty__title {
  margin: 0;
  font-size: var(--fontSizeBase400);
  font-weight: var(--fontWeightSemibold);
  line-height: var(--lineHeightBase400);
}
.empty__text {
  margin: 0;
  color: var(--uaf-text-muted);
}
.empty__action {
  margin-top: var(--spacingVerticalS);
}
</style>
