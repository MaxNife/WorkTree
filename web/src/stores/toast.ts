import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastIntent = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  intent: ToastIntent
  message: string
  /** Milliseconds before it closes by itself; 0 keeps it until dismissed. */
  timeout: number
}

export interface ToastOptions {
  timeout?: number
}

// Errors stay longer so they can be read; every toast pauses while hovered or focused (WCAG 2.2.1).
const DEFAULT_TIMEOUT: Record<ToastIntent, number> = { success: 5_000, info: 5_000, error: 10_000 }

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])
  const timers = new Map<number, ReturnType<typeof setTimeout>>()
  let nextId = 1

  function dismiss(id: number): void {
    clearTimeout(timers.get(id))
    timers.delete(id)
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  function schedule(toast: Toast): void {
    clearTimeout(timers.get(toast.id))
    if (toast.timeout > 0) timers.set(toast.id, setTimeout(() => dismiss(toast.id), toast.timeout))
  }

  function show(intent: ToastIntent, message: string, options: ToastOptions = {}): number {
    const toast: Toast = { id: nextId++, intent, message, timeout: options.timeout ?? DEFAULT_TIMEOUT[intent] }
    toasts.value = [...toasts.value, toast]
    schedule(toast)
    return toast.id
  }

  /** Stop the clock while the user is reading or interacting with a toast. */
  function pause(id: number): void {
    clearTimeout(timers.get(id))
    timers.delete(id)
  }

  function resume(id: number): void {
    const toast = toasts.value.find((t) => t.id === id)
    if (toast) schedule(toast)
  }

  return { toasts, show, dismiss, pause, resume }
})

/** Show short, self-closing notifications. They are announced through the shell's live regions. */
export function useToast() {
  const store = useToastStore()
  return {
    success: (message: string, options?: ToastOptions) => store.show('success', message, options),
    error: (message: string, options?: ToastOptions) => store.show('error', message, options),
    info: (message: string, options?: ToastOptions) => store.show('info', message, options),
    dismiss: (id: number) => store.dismiss(id),
  }
}

export type ToastApi = ReturnType<typeof useToast>
