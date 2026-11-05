<script setup lang="ts">
// "3 min ago" for recent times, a short date for older ones; the title holds the exact time.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { formatDateTime } from '@/format'

const REFRESH_MS = 30_000
const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const shortDate = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

const props = defineProps<{ value: string | null | undefined }>()

const now = ref(Date.now())
const date = computed(() => {
  const parsed = props.value ? new Date(props.value) : null
  return parsed && !Number.isNaN(parsed.getTime()) ? parsed : null
})
const text = computed(() => {
  if (!date.value) return '-'
  const age = now.value - date.value.getTime()
  if (age < MINUTE) return 'just now'
  if (age < HOUR) return `${Math.floor(age / MINUTE)} min ago`
  if (age < DAY) return `${Math.floor(age / HOUR)} h ago`
  if (age <= 30 * DAY) return `${Math.floor(age / DAY)} d ago`
  return shortDate.format(date.value)
})

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, REFRESH_MS)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <time :datetime="date ? (value ?? undefined) : undefined" :title="date ? formatDateTime(value) : undefined">{{ text }}</time>
</template>
