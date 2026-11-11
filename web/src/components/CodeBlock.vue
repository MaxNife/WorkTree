<script setup lang="ts">
// Read-only monospace text with a copy button. The scroll area takes focus so keyboards can scroll it.
import { useToast } from '@/stores/toast'
import UButton from './UButton.vue'

const props = defineProps<{ text: string; label: string; wrap?: boolean }>()
const toast = useToast()

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.text)
    toast.success('Copied to clipboard.')
  } catch {
    toast.error('Could not copy to the clipboard.')
  }
}
</script>

<template>
  <div class="code-block">
    <div class="code-block__bar">
      <span class="code-block__label">{{ label }}</span>
      <UButton class="code-block__copy" appearance="subtle" icon="copy" label="Copy to clipboard" @click="copy" />
    </div>
    <pre class="code-block__text" :class="{ 'code-block__text--wrap': wrap }" tabindex="0" :aria-label="label">{{ text }}</pre>
  </div>
</template>

<style scoped>
.code-block {
  overflow: hidden;
  border: var(--stroke-1) solid var(--wt-line);
  border-radius: var(--wt-radius-container);
  background: var(--wt-sunken);
}
.code-block__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  padding: var(--space-2) var(--space-4) var(--space-2) var(--space-12);
  border-bottom: var(--stroke-1) solid var(--wt-line);
  background: var(--wt-surface);
}
.code-block__label {
  overflow: hidden;
  color: var(--wt-muted);
  font-size: var(--font-size-12);
  font-weight: var(--weight-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.code-block__text {
  margin: 0;
  padding: var(--space-10) var(--space-12);
  color: var(--wt-ink);
  font-family: var(--wt-font-mono, monospace);
  font-size: var(--font-size-12);
  line-height: var(--line-height-20);
  overflow: auto;
}
.code-block__text:focus-visible {
  outline-offset: calc(-1 * var(--wt-focus-width));
}
.code-block__text--wrap {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
