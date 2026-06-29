<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useCall, Dialog, Button, FormControl, LoadingText } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { successToast, errorToast } from '@/lib/toast'
import type { BillingProfile, BillingGeo } from '@/types/billing'

// Edit the billing profile — currency (locked after activity), contact, address,
// and India GSTIN — shared by the Billing contact and Tax & compliance cards.
const open = defineModel<boolean>({ default: false })
const { activeTeam } = useSession()
const { currencyLocked, supportedCurrencies, reload: reloadSetup } = useBillingSetup()
const { profile: sharedProfile, reloadProfile } = useBillingOverview()

const profile = useCall<BillingProfile, { team: string }>({
  url: method(API.billingProfile),
  params: () => ({ team: activeTeam.value! }),
  immediate: false,
  refetch: true,
})
const geo = useCall<BillingGeo>({ url: method(API.billingGeo), immediate: false })
whenTeamReady(() => {
  profile.reload()
  geo.reload()
})

const FIELDS = [
  'currency', 'legal_name', 'email', 'phone', 'gstin',
  'address_line1', 'address_line2', 'city', 'state', 'country', 'pincode',
] as const
const form = reactive<Record<string, string>>({})
watch(
  () => profile.data ?? sharedProfile.data,
  (d) => {
    if (!d) return
    const row = d as unknown as Record<string, unknown>
    for (const f of FIELDS) form[f] = row[f]?.toString() ?? ''
  },
  { immediate: true },
)

const currencyOptions = computed(() =>
  supportedCurrencies.value.map((c) => ({ label: c, value: c })),
)
const countryOptions = computed(() =>
  (geo.data?.countries ?? []).map((c) => ({ label: c, value: c })),
)
const stateOptions = computed(() => geo.data?.india_states ?? [])
const isIndia = computed(() => form.country === 'India')

function optionModel(field: string) {
  return computed<{ label: string; value: string } | null>({
    get: () => (form[field] ? { label: form[field], value: form[field] } : null),
    set: (opt) => {
      form[field] = opt?.value ?? ''
    },
  })
}
const countryModel = optionModel('country')
const stateModel = optionModel('state')

const save = useCall<unknown, Record<string, unknown>>({
  url: method(API.saveBillingProfile),
  immediate: false,
})
async function submit(): Promise<void> {
  try {
    await save.submit({ team: activeTeam.value, ...form })
    successToast('Billing details saved.')
    await reloadSetup()
    reloadProfile()
    open.value = false
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <Dialog v-model:open="open" :options="{ title: 'Billing profile', size: '2xl' }">
    <template #body-content>
      <div v-if="profile.loading && !profile.data" class="space-y-3">
        <LoadingText :lines="6" />
      </div>

      <form v-else class="space-y-6" @submit.prevent="submit">
        <div class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Billing currency</h3>
          <FormControl
            v-model="form.currency"
            type="select"
            label="Billing currency *"
            :options="currencyOptions"
            :disabled="currencyLocked"
            :description="currencyLocked ? 'Locked — your team already has billing activity.' : ''"
          />
        </div>

        <div class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Contact</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl v-model="form.legal_name" label="Legal name *" />
            <FormControl v-model="form.email" type="email" label="Billing email" />
            <FormControl v-model="form.phone" label="Phone" />
          </div>
        </div>

        <div class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Address</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl v-model="form.address_line1" label="Address line 1 *" />
            <FormControl v-model="form.address_line2" label="Address line 2" />
            <FormControl v-model="form.city" label="City *" />
            <FormControl
              v-model="countryModel"
              type="autocomplete"
              label="Country *"
              placeholder="Select country"
              :options="countryOptions"
            />
            <FormControl
              v-if="isIndia"
              v-model="stateModel"
              type="autocomplete"
              label="State *"
              placeholder="Select state"
              :options="stateOptions"
            />
            <FormControl v-else v-model="form.state" label="State *" />
            <FormControl v-model="form.pincode" label="PIN code *" />
          </div>
        </div>

        <div v-if="isIndia" class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Tax details</h3>
          <FormControl
            v-model="form.gstin"
            label="GSTIN"
            description="Its first two digits must match the selected state."
          />
        </div>
      </form>
    </template>
    <template #actions>
      <Button
        variant="solid"
        label="Save"
        class="w-full"
        :loading="save.loading"
        @click="submit"
      />
    </template>
  </Dialog>
</template>
