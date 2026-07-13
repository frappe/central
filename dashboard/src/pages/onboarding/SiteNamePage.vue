<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Button, ErrorMessage, TextInput } from 'frappe-ui'
import { useRouter } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import { API } from '@/api/methods'
import { frappeErrorMessage, getFrappe, methodUrl, postFrappe } from '@/lib/auth'

type Availability = { available: boolean; reason: string | null; fqdn: string | null; domain: string }

const router = useRouter()
const subdomain = ref('')
const domain = ref('')
const checking = ref(false)
const creating = ref(false)
const availability = ref<Availability | null>(null)
const error = ref('')

let debounce: ReturnType<typeof setTimeout> | undefined

onMounted(async () => {
  try {
    const result = await getFrappe<{ domain: string }>(methodUrl(API.siteDomain))
    domain.value = result.domain
  } catch {
    // Non-fatal: the suffix is cosmetic until check runs, which returns it too.
  }
})

watch(subdomain, (value) => {
  availability.value = null
  error.value = ''
  clearTimeout(debounce)
  if (!value.trim()) return
  debounce = setTimeout(() => check(value.trim()), 400)
})

async function check(value: string) {
  checking.value = true
  try {
    const result = await getFrappe<Availability>(methodUrl(API.checkSubdomain), { subdomain: value })
    // Ignore a stale response if the user kept typing.
    if (value !== subdomain.value.trim()) return
    availability.value = result
    if (result.domain) domain.value = result.domain
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'Could not check that name.')
  } finally {
    checking.value = false
  }
}

async function createSite() {
  if (!availability.value?.available) return
  creating.value = true
  error.value = ''
  try {
    const result = await postFrappe<{ name: string }>(methodUrl(API.createSite), {
      subdomain: subdomain.value.trim(),
    })
    router.push(`/onboarding/provisioning/${encodeURIComponent(result.name)}`)
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'Could not create your site.')
    creating.value = false
  }
}
</script>

<template>
  <AuthShell show-progress :step="3">
    <h1 class="text-2xl font-semibold text-ink-gray-9">Name your site</h1>
    <p class="mt-2 text-base text-ink-gray-5">
      This is the web address you'll use to reach it. You can connect a custom domain later.
    </p>

    <form class="mt-8 space-y-4" @submit.prevent="createSite">
      <TextInput
        id="subdomain"
        v-model="subdomain"
        label="Site address"
        size="md"
        variant="subtle"
        placeholder="yourcompany"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        autofocus
        :error="availability && !availability.available ? availability.reason ?? '' : ''"
      >
        <template #suffix>
          <span v-if="domain" class="text-p-sm text-ink-gray-4">.{{ domain }}</span>
        </template>
        <template v-if="availability?.available" #description>
          <span class="flex items-center gap-1 text-ink-green-7">
            <span class="lucide-check size-4" aria-hidden="true" />
            <span><span class="font-medium">{{ availability.fqdn }}</span> is available</span>
          </span>
        </template>
        <template v-else-if="!availability" #description>
          Lowercase letters, numbers and hyphens.
        </template>
      </TextInput>

      <ErrorMessage v-if="error" :message="error" />
      <Button
        type="submit"
        variant="solid"
        size="md"
        class="w-full"
        :loading="creating"
        :disabled="!availability?.available || checking"
      >
        Continue
      </Button>
    </form>
  </AuthShell>
</template>
