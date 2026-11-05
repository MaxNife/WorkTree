<script setup lang="ts">
// The help and error text under a form control. The error has an icon and its own words, so it is
// not told apart by colour alone, and it is announced when it appears.
import { descriptionId, errorId } from './field'
import UIcon from './UIcon.vue'

defineProps<{ fieldId: string; description?: string; error?: string }>()
</script>

<template>
  <p v-if="description" :id="descriptionId(fieldId)" class="field-message">{{ description }}</p>
  <p v-if="error" :id="errorId(fieldId)" class="field-message field-message--error" role="alert">
    <UIcon name="error" />
    <span>{{ error }}</span>
  </p>
</template>

<style scoped>
.field-message {
  margin: 0;
  color: var(--uaf-text-muted);
  font-size: var(--fontSizeBase200);
  line-height: var(--lineHeightBase200);
  overflow-wrap: anywhere;
}
.field-message--error {
  display: flex;
  gap: var(--spacingHorizontalXS);
  color: var(--uaf-danger);
}
</style>
