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
    <pre class="code-block__text" :class="{ 'code-block__text--wrap': wrap }" tabindex="0" :aria-label="label">{{ text }}</pre>
    <UButton class="code-block__copy" appearance="subtle" icon="copy" label="Copy to clipboard" @click="copy" />
  </div>
</template>

<style scoped>
.code-block {
  position: relative;
}
.code-block__text {
  margin: 0;
  padding: var(--spacingVerticalS) var(--spacingHorizontalM);
  padding-inline-end: calc(var(--uaf-control-height) + var(--spacingHorizontalS));
  border: var(--strokeWidthThin) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface-sunken);
  color: var(--uaf-text);
  font-family: var(--uaf-font-mono, monospace);
  font-size: var(--fontSizeBase200);
  overflow: auto;
}
.code-block__text--wrap {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.code-block__copy {
  position: absolute;
  top: var(--spacingVerticalXS);
  right: var(--spacingHorizontalXS);
}
</style>
