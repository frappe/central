<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useCall, Button, FormControl, LoadingText } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { successToast, errorToast } from '@/lib/toast'
import type { BillingProfile, BillingGeo } from '@/types/billing'

// Step 1 — currency + legal name + address (+ tax). Saving completes the billing
// profile, which is what unlocks every money-moving action. Currency is chosen
// here and locks once activity begins, so it can never be guessed wrong later.
defineProps<{ active?: boolean; complete?: boolean }>()
const emit = defineEmits<{ 'update:complete': [value: boolean]; advance: [] }>()

const { activeTeam } = useSession()
const { complete: setupComplete, supportedCurrencies, reload: reloadSetup } = useBillingSetup()

// Mirror the shared completion flag up to the wizard (immediate handles revisits
// where the profile is already complete).
watch(setupComplete, (v) => emit('update:complete', v), { immediate: true })

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
  'currency', 'legal_name', 'email', 'gstin',
  'address_line1', 'address_line2', 'city', 'state', 'country', 'pincode',
] as const
const form = reactive<Record<string, string>>({})
watch(
  () => profile.data,
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
// India drives the state dropdown — its value's GST code validates the GSTIN.
const isIndia = computed(() => form.country === 'India')

// Autocomplete works in {label, value} options; the profile stores plain strings,
// so proxy between the two.
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

const required = ['currency', 'legal_name', 'address_line1', 'city', 'state', 'country', 'pincode']
const canSubmit = computed(() => required.every((f) => String(form[f] || '').trim()))

const save = useCall<unknown, Record<string, unknown>>({
  url: method(API.saveBillingProfile),
  immediate: false,
})
async function submit(): Promise<void> {
  try {
    await save.submit({ team: activeTeam.value, ...form })
    await reloadSetup() // refresh shared state → flips completion, unlocks actions
    successToast('Billing profile saved.')
    emit('advance') // let the wizard open the next step
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <div v-if="profile.loading && !profile.data" class="space-y-3">
    <LoadingText :lines="6" />
  </div>

  <form v-else class="space-y-4" @submit.prevent="submit">
    <!-- Grouped into Currency / Contact / Address / Tax for hierarchy. Once
         complete the fieldset disables every control and Save is hidden; edits
         happen later in Billing settings. -->
    <fieldset :disabled="complete" class="space-y-6">
      <div class="space-y-3">
        <h3 class="text-sm font-medium text-ink-gray-8">Billing currency</h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="form.currency"
            type="select"
            label="Currency *"
            :options="currencyOptions"
          />
          <p v-if="!currencyOptions.length" class="self-end text-p-sm text-ink-amber-3">
            No billing currencies are available yet — ask an admin to enable a payment gateway
            with a default currency.
          </p>
        </div>
      </div>

      <div class="space-y-3">
        <h3 class="text-sm font-medium text-ink-gray-8">Contact</h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl v-model="form.legal_name" label="Legal name *" />
          <FormControl v-model="form.email" type="email" label="Billing email" />
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
        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            v-model="form.gstin"
            label="GSTIN"
            description="Its first two digits must match the selected state."
          />
        </div>
      </div>
    </fieldset>

    <div v-if="!complete" class="flex items-center gap-3 pt-1">
      <Button
        variant="solid"
        label="Save & continue"
        type="submit"
        :loading="save.loading"
        :disabled="!canSubmit"
      />
      <span v-if="!canSubmit" class="text-p-sm text-ink-gray-5">
        Fill the fields marked * to continue.
      </span>
    </div>
  </form>
</template>
