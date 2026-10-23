<script setup lang="ts">
// Plain text only: no illustration or icon. Say what is missing and, if possible, how to fix it.
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <section class="empty" aria-label="Nothing here yet">
    <h2 class="empty__title">{{ title }}</h2>
    <p v-if="description" class="empty__text">{{ description }}</p>
    <div class="empty__action"><slot /></div>
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
  font-size: var(--fontSizeBase400);
}
.empty__text {
  margin: 0;
  color: var(--uaf-text-muted);
}
.empty__action:empty {
  display: none;
}
.empty__action {
  margin-top: var(--spacingVerticalS);
}
</style>
