<script setup lang="ts">
import { ref } from 'vue'
import { Button, ErrorMessage } from 'frappe-ui'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import { frappeErrorMessage, postFrappe } from '@/lib/auth'

const route = useRoute()
const email = String(route.query.email ?? '')
const loading = ref(false)
const sent = ref(false)
const error = ref('')

async function resend() {
  if (!email) return
  loading.value = true
  sent.value = false
  error.value = ''
  try {
    await postFrappe('/api/method/frappe.core.doctype.user.user.reset_password', {
      user: email,
    })
    sent.value = true
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'Could not resend the email.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthShell show-progress :step="2">
    <div class="mb-6 grid size-10 place-items-center rounded-5 bg-surface-green-2 text-ink-green-3">
      <span class="lucide-mail-check size-5" aria-hidden="true" />
    </div>
    <h1 class="text-2xl font-semibold text-ink-gray-9">Check your email</h1>
    <p class="mt-2 text-base text-ink-gray-5">
      We sent a secure registration link to
      <span class="font-medium text-ink-gray-8">{{ email || 'your email address' }}</span>.
      Open it to set your password and continue.
    </p>

    <p v-if="sent" class="mt-6 rounded bg-surface-green-2 px-3 py-2 text-p-sm text-ink-green-3">
      A new registration email has been sent.
    </p>
    <ErrorMessage v-if="error" class="mt-6" :message="error" />

    <Button
      v-if="email"
      variant="outline"
      size="md"
      class="mt-8 w-full"
      :loading="loading"
      @click="resend"
    >
      Send again
    </Button>

    <p class="mt-6 text-center text-p-sm text-ink-gray-5">
      Wrong email?
      <RouterLink class="font-medium text-ink-gray-8 hover:text-ink-gray-9" to="/signup">
        Go back
      </RouterLink>
    </p>
  </AuthShell>
</template>
