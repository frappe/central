<script setup lang="ts">
import { ref } from 'vue'
import { Button, ErrorMessage } from 'frappe-ui'
import AuthShell from '@/components/auth/AuthShell.vue'
import ValidatedFormControl from '@/formComponents/ValidatedFormControl.vue'
import { emailError, frappeErrorMessage, postFrappe } from '@/lib/auth'

const email = ref('')
const submitted = ref(false)
const loading = ref(false)
const sent = ref(false)
const error = ref('')

async function resetPassword() {
  submitted.value = true
  error.value = ''
  if (emailError(email.value)) return

  loading.value = true
  try {
    await postFrappe('/api/method/frappe.core.doctype.user.user.reset_password', {
      user: email.value.trim(),
    })
    sent.value = true
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'Could not send reset instructions.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthShell>
    <template v-if="!sent">
      <h1 class="text-2xl font-semibold text-ink-gray-9">Reset your password</h1>
      <p class="mt-1 text-base text-ink-gray-5">
        We’ll email you a secure link to choose a new password.
      </p>

      <form class="mt-8 space-y-4" novalidate @submit.prevent="resetPassword">
        <ValidatedFormControl
          v-model="email"
          label="Work email"
          type="email"
          autocomplete="email"
          placeholder="you@company.com"
          :validator="emailError"
          :submitted="submitted"
        />
        <ErrorMessage v-if="error" :message="error" />
        <Button type="submit" variant="solid" size="md" class="w-full" :loading="loading">
          Send reset link
        </Button>
      </form>
    </template>

    <template v-else>
      <div class="mb-6 grid size-10 place-items-center rounded-5 bg-surface-green-2 text-ink-green-3">
        <span class="lucide-mail-check size-5" aria-hidden="true" />
      </div>
      <h1 class="text-2xl font-semibold text-ink-gray-9">Check your email</h1>
      <p class="mt-2 text-base text-ink-gray-5">
        If an account exists for <span class="font-medium text-ink-gray-8">{{ email }}</span>,
        password reset instructions are on their way.
      </p>
    </template>

    <p class="mt-6 text-center text-p-sm text-ink-gray-5">
      <RouterLink class="font-medium text-ink-gray-8 hover:text-ink-gray-9" to="/login">
        Back to sign in
      </RouterLink>
    </p>
  </AuthShell>
</template>
