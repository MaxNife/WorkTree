// What the form controls share: the ids of the description and error text under a field.
import { computed, useId } from 'vue'

export interface FieldMessageProps {
  description?: string
  error?: string
}

export const descriptionId = (fieldId: string): string => `${fieldId}-description`
export const errorId = (fieldId: string): string => `${fieldId}-error`

export function useFieldMessages(props: Readonly<FieldMessageProps>) {
  const fieldId = useId()
  const describedBy = computed(() => {
    const ids = [props.error ? errorId(fieldId) : '', props.description ? descriptionId(fieldId) : '']
    return ids.filter(Boolean).join(' ') || undefined
  })
  return { fieldId, describedBy }
}
