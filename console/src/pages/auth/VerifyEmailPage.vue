<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, ErrorMessage } from 'frappe-ui'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import OtpInput from '@/components/common/OtpInput.vue'
import { API } from '@/api/methods'
import { frappeErrorMessage, methodUrl, postFrappe } from '@/lib/auth'

const route = useRoute()
const router = useRouter()
const email = queryString(route.query.email)
const product = computed(() => queryString(route.query.product))
const isProductSignup = computed(() => Boolean(product.value))
const signupSteps = computed(() => (isProductSignup.value ? 4 : 2))

const otp = ref('')
const loading = ref(false)
const redirecting = ref(false)
const resent = ref(false)
const error = ref('')
const devHint = import.meta.env.DEV

async function verify() {
  if (loading.value || otp.value.length !== 6) return
  loading.value = true
  error.value = ''
  try {
    await postFrappe(methodUrl(API.verifySignup), { email, code: otp.value })
    // Full navigation so the SPA re-boots with the now-authenticated session.
    // `replace` (not `href`) so the verify page leaves the back stack — Back from
    // the next screen can't land on it (the guard also resumes authenticated state).
    redirecting.value = true
    window.location.replace(signupDestination())
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'That code did not work. Please try again.')
    otp.value = ''
  } finally {
    if (!redirecting.value) loading.value = false
  }
}

async function resend() {
  if (loading.value || !email) return
  loading.value = true
  resent.value = false
  error.value = ''
  try {
    await postFrappe(methodUrl(API.resendSignupCode), { email })
    resent.value = true
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'Could not resend the code.')
  } finally {
    loading.value = false
  }
}

function signupDestination(): string {
  return isProductSignup.value ? '/dashboard/onboarding/site' : '/dashboard/servers'
}

function signupQuery(): LocationQueryRaw | undefined {
  if (!isProductSignup.value) return undefined
  return { product: product.value }
}

function queryString(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return queryString(value[0])
  return ''
}
</script>

<template>
  <AuthShell show-progress :step="2" :steps="signupSteps">
    <h1 class="text-2xl font-semibold text-ink-gray-9">Verify your email</h1>
    <p class="mt-2 text-base text-ink-gray-5">
      Enter the 6-digit code we sent to
      <span class="font-medium text-ink-gray-8">{{ email || 'your email address' }}</span>.
    </p>

    <form class="mt-8 space-y-4" @submit.prevent="verify">
      <OtpInput
        v-model="otp"
        label="Verification code"
        :disabled="loading"
        autofocus
        @complete="verify"
      />
      <p v-if="devHint" class="text-p-sm text-ink-gray-4">Demo — any 6 digits work.</p>

      <p v-if="resent" class="rounded bg-surface-green-2 px-3 py-2 text-p-sm text-ink-green-3">
        A new code has been sent.
      </p>
      <ErrorMessage v-if="error" :message="error" />

      <Button
        type="submit"
        variant="solid"
        size="md"
        class="w-full"
        :loading="loading"
        :disabled="otp.length !== 6"
      >
        Verify and continue
      </Button>
    </form>

    <div class="mt-6 flex items-center justify-between text-p-sm">
      <button
        type="button"
        class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
        @click="router.push({ path: '/signup', query: signupQuery() })"
      >
        Use a different email
      </button>
      <button
        type="button"
        class="font-medium text-ink-gray-8 hover:text-ink-gray-9 disabled:opacity-50"
        :disabled="loading"
        @click="resend"
      >
        Resend code
      </button>
    </div>
  </AuthShell>
</template>
