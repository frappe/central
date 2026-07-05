<script setup lang="ts">
import { computed } from 'vue'
import { Button, ErrorMessage, FormControl } from 'frappe-ui'
import MinimalAuthShell from '@/components/auth/MinimalAuthShell.vue'
import SocialLoginButtons from '@/components/auth/SocialLoginButtons.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import { useAuth } from '@/composables/useAuth'
import { useSignup } from '@/composables/useSignup'
import { emailError, requiredError } from '@/lib/auth'

const { providerLogins } = useAuth()
const { fullName, email, country, countries, submitted, loading, error, product, isProductSignup, signup } =
  useSignup()

// Product signups land straight in site onboarding after signing in — carry the
// product so that screen keeps its name and logo instead of falling back to generic copy.
const signInRoute = computed(() => {
  if (!isProductSignup.value) return { path: '/login' }
  const target = `/dashboard/onboarding/site?product=${encodeURIComponent(product.value)}`
  return { path: '/login', query: { 'redirect-to': target } }
})
</script>

<template>
  <MinimalAuthShell>
    <h1 class="text-xl font-semibold text-ink-gray-8">
      Create your account
    </h1>

    <form class="mt-6 space-y-4" novalidate @submit.prevent="signup">
      <ValidatedFormControl
        v-model="fullName"
        label="Full name"
        autocomplete="name"
        placeholder="John Doe"
        autofocus
        :validator="requiredError('Full name')"
        :submitted="submitted"
      />
      <ValidatedFormControl
        v-model="email"
        label="Work email"
        type="email"
        autocomplete="email"
        placeholder="username@company.com"
        :validator="emailError"
        :submitted="submitted"
      />
      <FormControl
        v-model="country"
        type="select"
        label="Country"
        size="md"
        variant="subtle"
        :options="countries"
      />

      <Transition name="error-fade">
        <ErrorMessage v-if="error" :message="error" />
      </Transition>
      <Button type="submit" variant="solid" size="md" class="mt-2 w-full" :loading="loading">
        Continue
      </Button>
    </form>

    <SocialLoginButtons v-if="!isProductSignup" :providers="providerLogins" prefix="Continue with" />

    <p class="mt-4 text-center text-p-sm text-ink-gray-5">
      Already have an account?
      <RouterLink class="font-medium text-ink-gray-8 hover:text-ink-gray-9" :to="signInRoute">
        Sign in
      </RouterLink>
    </p>
  </MinimalAuthShell>
</template>
