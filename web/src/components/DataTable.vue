<script setup lang="ts" generic="T">
// A compact native table. Rows are one tab stop (roving tabindex) when they can be opened. Sticky
// headers stick to the nearest scroll container, so this adds no scrolling wrapper of its own.
import { computed, getCurrentInstance, ref } from 'vue'
import UIcon from './UIcon.vue'

export interface DataTableColumn {
  key: string
  label: string
  sortable?: boolean
  align?: 'start' | 'end'
  width?: string
}

const props = defineProps<{
  columns: DataTableColumn[]
  rows: T[]
  rowKey: (row: T) => string
  caption: string
  selectedKey?: string
  rowLabel?: (row: T) => string
}>()
const sort = defineModel<string>('sort')
const emit = defineEmits<{ 'row-open': [row: T] }>()
defineSlots<{ [K: `cell-${string}`]: (props: { row: T; value: unknown }) => unknown }>()

// A click on one of these inside a row belongs to that control, not to the row.
const NESTED_CONTROLS =
  'a, button, input, select, textarea, label, summary, [role="button"], [role="link"], [tabindex]'

const body = ref<HTMLElement>()
const focusedKey = ref<string>()
const hasOpenListener = Boolean(getCurrentInstance()?.vnode.props?.onRowOpen)
const interactive = computed(() => hasOpenListener || props.selectedKey !== undefined)

const tabStop = computed(() => {
  const keys = props.rows.map((row) => props.rowKey(row))
  if (focusedKey.value !== undefined && keys.includes(focusedKey.value)) return focusedKey.value
  if (props.selectedKey !== undefined && keys.includes(props.selectedKey)) return props.selectedKey
  return keys[0]
})

function sortState(column: DataTableColumn): 'ascending' | 'descending' | 'none' {
  if (sort.value === column.key) return 'ascending'
  if (sort.value === `-${column.key}`) return 'descending'
  return 'none'
}

function toggleSort(column: DataTableColumn): void {
  sort.value = sort.value === `-${column.key}` ? column.key : `-${column.key}`
}

function cellValue(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function cellText(row: T, key: string): string {
  const value = cellValue(row, key)
  return value === null || value === undefined ? '-' : String(value)
}

function onRowClick(event: MouseEvent, row: T): void {
  const control = (event.target as Element).closest(NESTED_CONTROLS)
  if (interactive.value && (!control || control === event.currentTarget)) emit('row-open', row)
}

function onRowKeydown(event: KeyboardEvent, row: T, index: number): void {
  if (!interactive.value || event.target !== event.currentTarget) return
  if (event.key === 'Enter') {
    event.preventDefault()
    emit('row-open', row)
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const next = body.value?.children[index + (event.key === 'ArrowDown' ? 1 : -1)]
    ;(next as HTMLElement | undefined)?.focus()
  }
}
</script>

<template>
  <table class="data-table">
    <caption class="data-table__caption">{{ caption }}</caption>
    <thead>
      <tr>
        <th
          v-for="column in columns"
          :key="column.key"
          scope="col"
          :class="{ 'data-table__cell--end': column.align === 'end' }"
          :style="column.width ? { width: column.width } : undefined"
          :aria-sort="column.sortable ? sortState(column) : undefined"
        >
          <button v-if="column.sortable" class="data-table__sort" type="button" @click="toggleSort(column)">
            {{ column.label }}
            <UIcon v-if="sortState(column) === 'ascending'" name="chevron-up" :size="12" />
            <UIcon v-else-if="sortState(column) === 'descending'" name="chevron-down" :size="12" />
          </button>
          <template v-else>{{ column.label }}</template>
        </th>
      </tr>
    </thead>
    <tbody ref="body">
      <tr
        v-for="(row, index) in rows"
        :key="rowKey(row)"
        class="data-table__row"
        :class="{
          'data-table__row--interactive': interactive,
          'data-table__row--selected': selectedKey !== undefined && rowKey(row) === selectedKey,
        }"
        :tabindex="interactive ? (rowKey(row) === tabStop ? 0 : -1) : undefined"
        :aria-label="rowLabel?.(row)"
        :aria-current="selectedKey !== undefined && rowKey(row) === selectedKey ? 'true' : undefined"
        @click="onRowClick($event, row)"
        @keydown="onRowKeydown($event, row, index)"
        @focus="focusedKey = rowKey(row)"
      >
        <td v-for="column in columns" :key="column.key" :class="{ 'data-table__cell--end': column.align === 'end' }">
          <slot :name="`cell-${column.key}`" :row="row" :value="cellValue(row, column.key)">{{ cellText(row, column.key) }}</slot>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.data-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
}
.data-table__caption {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
th,
td {
  height: var(--uaf-row-height);
  padding: var(--uaf-cell-padding);
  border-bottom: var(--stroke-1) solid var(--uaf-border);
  text-align: start;
}
th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--uaf-surface);
  color: var(--uaf-text-muted);
  font-size: var(--font-size-12);
  font-weight: var(--weight-semibold);
}
.data-table__cell--end {
  text-align: end;
}
.data-table__sort {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.data-table__sort:hover {
  color: var(--uaf-text);
}
.data-table__row:hover {
  background: var(--uaf-surface-hover);
}
.data-table__row--selected,
.data-table__row--selected:hover {
  background: var(--uaf-surface-selected);
}
.data-table__row--interactive {
  cursor: pointer;
}
.data-table__row:focus-visible {
  outline: var(--stroke-2) solid var(--uaf-focus);
  outline-offset: calc(var(--stroke-2) * -1);
}
</style>
