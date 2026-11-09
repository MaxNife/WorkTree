<script setup lang="ts" generic="T">
// Items in side-by-side columns, read-only (no drag and drop). The caller renders each card.
import { formatCount } from '@/format'

defineProps<{ columns: { id: string; title: string; items: T[] }[]; itemKey: (item: T) => string }>()
defineSlots<{ default(props: { item: T }): unknown }>()
</script>

<template>
  <div class="board" tabindex="0" role="group" aria-label="Board columns">
    <section v-for="column in columns" :key="column.id" class="board__column" :aria-label="column.title">
      <div class="board__header">
        <span class="board__title">{{ column.title }}</span>
        <span class="board__count">{{ formatCount(column.items.length) }}</span>
      </div>
      <ul class="board__items">
        <li v-for="item in column.items" :key="itemKey(item)"><slot :item="item" /></li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.board {
  display: flex;
  align-items: flex-start;
  gap: var(--uaf-gap);
  overflow-x: auto;
}
.board__column {
  flex: 0 0 280px;
  padding: var(--uaf-gap);
  border: var(--stroke-1) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface-sunken);
}
.board__header {
  display: flex;
  justify-content: space-between;
  gap: var(--uaf-gap);
  margin-bottom: var(--uaf-gap);
}
.board__title {
  font-weight: var(--weight-semibold);
}
.board__count {
  color: var(--uaf-text-muted);
}
.board__items {
  display: grid;
  gap: var(--uaf-gap);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
