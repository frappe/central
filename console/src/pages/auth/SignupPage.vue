<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, ErrorMessage } from 'frappe-ui'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import SocialLoginButtons from '@/components/auth/SocialLoginButtons.vue'
import { useAuth } from '@/composables/useAuth'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import { emailError, frappeErrorMessage, postFrappe, requiredError } from '@/lib/auth'

const route = useRoute()
const router = useRouter()
const fullName = ref('')
const email = ref('')
const submitted = ref(false)
const loading = ref(false)
const error = ref('')

const { providerLogins } = useAuth()
const product = computed(() => queryString(route.query.product))
const isProductSignup = computed(() => Boolean(product.value))
const signupSteps = computed(() => (isProductSignup.value ? 4 : 2))
const subheading = computed(() => (
  isProductSignup.value
    ? 'A couple of minutes from here to naming your first site.'
    : 'Verify your email to start managing Central instances.'
))

async function signup() {
  submitted.value = true
  error.value = ''
  if (requiredError('Full name')(fullName.value) || emailError(email.value)) return

  loading.value = true
  try {
    const response = await postFrappe<[number, string]>(
      '/api/method/central.api.auth.sign_up',
      {
        full_name: fullName.value.trim(),
        email: email.value.trim(),
      },
    )
    const [status, message] = response ?? [0, 'Unable to create your account.']
    if (status !== 1) {
      error.value = message
      return
    }
    await router.push({
      path: '/signup/verify',
      query: verificationQuery(),
    })
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'Unable to create your account.')
  } finally {
    loading.value = false
  }
}

function verificationQuery(): LocationQueryRaw {
  return {
    email: email.value.trim(),
    ...(product.value ? { product: product.value } : {}),
  }
}

function loginQuery(): LocationQueryRaw | undefined {
  if (!isProductSignup.value) return undefined
  return { 'redirect-to': '/dashboard/onboarding/site' }
}

function queryString(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return queryString(value[0])
  return ''
}
</script>

<template>
  <AuthShell show-progress :steps="signupSteps">
    <h1 class="text-2xl font-semibold text-ink-gray-9">
      Create your account
    </h1>
    <p class="mt-1 text-base text-ink-gray-5">
      {{ subheading }}
    </p>

    <form class="mt-8 space-y-4" novalidate @submit.prevent="signup">
      <ValidatedFormControl
        v-model="fullName"
        label="Full name"
        autocomplete="name"
        placeholder="Jane Doe"
        autofocus
        :validator="requiredError('Full name')"
        :submitted="submitted"
      />
      <ValidatedFormControl
        v-model="email"
        label="Work email"
        type="email"
        autocomplete="email"
        placeholder="jane@company.com"
        :validator="emailError"
        :submitted="submitted"
      />

      <ErrorMessage v-if="error" :message="error" />
      <Button type="submit" variant="solid" size="md" class="w-full" :loading="loading">
        Continue
      </Button>
    </form>

    <SocialLoginButtons :providers="providerLogins" prefix="Continue with" />

    <p class="mt-6 text-center text-p-sm text-ink-gray-5">
      Already have an account?
      <RouterLink
        class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
        :to="{ path: '/login', query: loginQuery() }"
      >
        Sign in
      </RouterLink>
    </p>
  </AuthShell>
</template>
