<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Button, ErrorMessage, TextInput } from 'frappe-ui'
import { useRoute, useRouter } from 'vue-router'
import MinimalAuthShell from '@/components/auth/MinimalAuthShell.vue'
import { API } from '@/api/methods'
import { frappeErrorMessage, getFrappe, methodUrl, postFrappe } from '@/lib/auth'
import { productInfo } from '@/lib/products'

type Availability = { available: boolean; reason: string | null; fqdn: string | null; domain: string }

const route = useRoute()
const router = useRouter()
const product = computed(() => {
  const slug = route.query.product
  return typeof slug === 'string' ? productInfo(slug) : null
})

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
    router.push({
      path: `/onboarding/provisioning/${encodeURIComponent(result.name)}`,
      // Keep the product along so provisioning can say which app it installs.
      query: typeof route.query.product === 'string' ? { product: route.query.product } : undefined,
    })
  } catch (exception) {
    error.value = frappeErrorMessage(exception, 'Could not create your site.')
    creating.value = false
  }
}
</script>

<template>
  <MinimalAuthShell>
    <div class="flex items-center gap-2">
      <img v-if="product" :src="product.logo" alt="" class="size-6" />
      <h1 class="text-xl font-semibold text-ink-gray-8">
        {{ product ? `Set up ${product.name} on your site` : 'Set up your site' }}
      </h1>
    </div>

    <form class="mt-6" @submit.prevent="createSite">
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

      <ul class="mt-4 space-y-2.5 text-p-sm text-ink-gray-6">
        <li class="flex items-center gap-2">
          <span class="lucide-server size-4" aria-hidden="true" />
          Runs on its own private server near you.
        </li>
        <li class="flex items-center gap-2">
          <span class="lucide-gift size-4" aria-hidden="true" />
          Free with your $25 credits.
        </li>
        <li class="flex items-center gap-2">
          <span class="lucide-pencil-line size-4" aria-hidden="true" />
          Change plan anytime.
        </li>
      </ul>

      <Transition name="error-fade">
        <ErrorMessage v-if="error" class="mt-4" :message="error" />
      </Transition>
      <Button
        type="submit"
        variant="solid"
        size="md"
        class="mt-6 w-full"
        :loading="creating"
        :disabled="!availability?.available || checking"
      >
        Create my site
      </Button>
    </form>
  </MinimalAuthShell>
</template>
