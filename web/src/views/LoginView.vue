<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import MessageBar from '@/components/shell/MessageBar.vue'
import UButton from '@/components/UButton.vue'
import UTextInput from '@/components/UTextInput.vue'
import WorkTreeLogo from '@/components/WorkTreeLogo.vue'
import { safeRedirect } from '@/router/types'
import { useSession } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const session = useSession()

const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

function describe(failure: unknown): string {
  if (failure instanceof ApiError) {
    if (failure.status === 401) return 'The username or password is incorrect.'
    return failure.message
  }
  return 'Could not reach the server. Check your connection and try again.'
}

async function submit(): Promise<void> {
  if (busy.value) return
  if (!username.value.trim() || !password.value) {
    error.value = 'Enter your username and password.'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await session.login(username.value.trim(), password.value)
    await router.replace(safeRedirect(route.query.redirect) ?? '/')
  } catch (failure) {
    password.value = ''
    error.value = describe(failure)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <form class="login__card" aria-labelledby="login-title" novalidate @submit.prevent="submit">
      <WorkTreeLogo :size="28" />
      <h1 id="login-title" class="login__title">Sign in</h1>
      <MessageBar v-if="error" intent="error">{{ error }}</MessageBar>
      <UTextInput v-model="username" label="Username" autocomplete="username" :disabled="busy" />
      <UTextInput v-model="password" label="Password" type="password" autocomplete="current-password" :disabled="busy" />
      <UButton type="submit" appearance="primary" :disabled="busy">{{ busy ? 'Signing in...' : 'Sign in' }}</UButton>
    </form>
  </main>
</template>

<style scoped>
.login {
  display: grid;
  place-items: center;
  min-height: 100%;
  padding: var(--spacingVerticalXXL) var(--spacingHorizontalL);
  background: var(--uaf-surface-sunken);
}
.login__card {
  display: grid;
  gap: var(--spacingVerticalM);
  width: min(360px, 100%);
  padding: var(--spacingVerticalXXL) var(--spacingHorizontalXXL);
  border: var(--strokeWidthThin) solid var(--uaf-border);
  border-radius: var(--uaf-radius-container);
  background: var(--uaf-surface);
}
.login__title {
  font-size: var(--fontSizeBase500);
  line-height: var(--lineHeightBase500);
}
</style>
