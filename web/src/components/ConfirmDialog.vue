<script setup lang="ts">
// Ask before an action. The caller runs the action on `confirm`, sets `busy` meanwhile and closes it.
import { computed, ref, watch } from 'vue'
import UButton from './UButton.vue'
import UDialog from './UDialog.vue'
import UTextArea from './UTextArea.vue'

const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{
  title: string
  message: string
  confirmLabel: string
  // A destructive confirm (cancel, delete) fills with Hibiscus deep; the label still names the action.
  danger?: boolean
  reasonLabel?: string
  reasonRequired?: boolean
  busy?: boolean
}>()
const emit = defineEmits<{ confirm: [reason: string] }>()

const reason = ref('')
const trimmedReason = computed(() => reason.value.trim())
const reasonMissing = computed(() => Boolean(props.reasonLabel && props.reasonRequired) && !trimmedReason.value)

watch(open, (isOpen) => {
  if (isOpen) reason.value = ''
})
</script>

<template>
  <UDialog v-model:open="open" :title="title" size="small">
    <p class="confirm__message">{{ message }}</p>
    <UTextArea v-if="reasonLabel" v-model="reason" :label="reasonLabel" :required="reasonRequired" />
    <template #footer>
      <UButton @click="open = false">Cancel</UButton>
      <UButton :appearance="danger ? 'destructive' : 'primary'" :disabled="busy || reasonMissing" @click="emit('confirm', trimmedReason)">
        {{ confirmLabel }}
      </UButton>
    </template>
  </UDialog>
</template>

<style scoped>
.confirm__message {
  margin: 0 0 var(--space-12);
}
</style>
