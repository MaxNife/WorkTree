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
        <li v-for="item in column.items" :key="itemKey(item)" class="board__item"><slot :item="item" /></li>
        <li v-if="column.items.length === 0" class="board__none">Nothing here</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.board {
  display: flex;
  align-items: flex-start;
  gap: var(--space-12);
  overflow-x: auto;
  padding-bottom: var(--space-4);
}
.board__column {
  display: grid;
  gap: var(--space-8);
  flex: 0 0 280px;
  padding: var(--space-10);
  border-radius: var(--wt-radius-container);
  background: var(--wt-sunken);
}
.board__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wt-gap);
  padding: var(--space-2) var(--space-4);
}
.board__title {
  font-weight: var(--weight-semibold);
}
.board__count {
  min-width: 22px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-full);
  background: var(--wt-surface);
  color: var(--wt-muted);
  font-size: var(--font-size-12);
  font-weight: var(--weight-semibold);
  line-height: var(--line-height-20);
  text-align: center;
}
.board__items {
  display: grid;
  gap: var(--space-8);
  margin: 0;
  padding: 0;
  list-style: none;
}
.board__item {
  padding: var(--space-10) var(--space-12);
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius);
  background: var(--wt-surface);
  overflow-wrap: anywhere;
}
.board__none {
  padding: var(--space-12);
  border: var(--stroke-1) dashed var(--wt-line-strong);
  border-radius: var(--wt-radius);
  color: var(--wt-muted);
  font-size: var(--font-size-12);
  text-align: center;
}
</style>
