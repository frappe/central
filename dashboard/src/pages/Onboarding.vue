<script setup>
import { computed, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCall } from 'frappe-ui'
import { Button, FormControl, LoadingText } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { successToast, errorToast } from '@/utils/toast'

// First-run billing setup, rendered in the content area while the shell's
// billing/settings options stay locked. The router sends a team here whenever its
// billing profile is incomplete; once currency + legal name + address are saved
// the options unlock and the team proceeds to the dashboard. Currency is chosen
// here (and locks once money moves), so it can never be guessed wrong later.
const route = useRoute()
const router = useRouter()
const { currentTeam } = useTeam()
const { supportedCurrencies, reload: reloadSetup } = useBillingSetup()

const profile = useCall({
  url: m(API.billingProfile),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

const FIELDS = [
  'currency', 'legal_name', 'email', 'gstin',
  'address_line1', 'address_line2', 'city', 'state', 'country', 'pincode',
]
const form = reactive({})
watch(
  () => profile.data,
  (d) => {
    if (!d) return
    for (const f of FIELDS) form[f] = d[f] ?? ''
  },
  { immediate: true },
)

const currencyOptions = computed(() => supportedCurrencies.value.map((c) => ({ label: c, value: c })))
const required = ['currency', 'legal_name', 'address_line1', 'city', 'state', 'country', 'pincode']
const canSubmit = computed(() => required.every((f) => String(form[f] || '').trim()))

const save = useCall({ url: m(API.saveBillingProfile), method: 'POST', immediate: false })
async function submit() {
  try {
    await save.submit({ team: currentTeam.value, ...form })
    await reloadSetup() // refresh shared state → unlocks the sidebar options
    successToast('Billing profile set up.')
    router.replace(route.query.redirect || '/billing')
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto w-full max-w-2xl px-5 py-8">
      <div class="rounded-lg border border-outline-gray-1 bg-surface-white p-6">
        <h1 class="text-lg text-ink-gray-9">Set up billing for your team</h1>
        <p class="mt-1 text-p-sm text-ink-gray-5">
          Choose your billing currency and add your company details to get started — this is
          needed before you can add credits or a payment method, and it unlocks the rest of
          billing. Your currency locks once activity begins, so pick carefully.
        </p>

        <div v-if="profile.loading && !profile.data" class="mt-6 space-y-3">
          <LoadingText :lines="6" />
        </div>

        <form v-else class="mt-6 space-y-4" @submit.prevent="submit">
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl
              type="select"
              v-model="form.currency"
              label="Billing currency *"
              :options="currencyOptions"
            />
            <div />
            <FormControl v-model="form.legal_name" label="Legal name *" />
            <FormControl v-model="form.gstin" label="GSTIN" />
            <FormControl v-model="form.email" type="email" label="Billing email" />
            <FormControl v-model="form.address_line1" label="Address line 1 *" />
            <FormControl v-model="form.address_line2" label="Address line 2" />
            <FormControl v-model="form.city" label="City *" />
            <FormControl v-model="form.state" label="State *" />
            <FormControl v-model="form.country" label="Country *" />
            <FormControl v-model="form.pincode" label="PIN code *" />
          </div>

          <div class="flex items-center gap-3 pt-2">
            <Button
              variant="solid"
              label="Finish setup"
              type="submit"
              :loading="save.loading"
              :disabled="!canSubmit"
            />
            <span v-if="!canSubmit" class="text-p-sm text-ink-gray-5">
              Fill the fields marked * to continue.
            </span>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
