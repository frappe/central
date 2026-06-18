<script setup>
import { computed, reactive, watch } from 'vue'
import { useCall } from 'frappe-ui'
import { Button, FormControl, LoadingText } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { successToast, errorToast } from '@/utils/toast'

// Step 1 — currency + legal name + address (+ tax). Saving completes the billing
// profile, which is what unlocks every money-moving action. Currency is chosen
// here and locks once activity begins, so it can never be guessed wrong later.
defineProps({ active: Boolean, complete: Boolean })
const emit = defineEmits(['update:complete', 'advance'])

const { currentTeam } = useTeam()
const { complete: setupComplete, supportedCurrencies, reload: reloadSetup } = useBillingSetup()

// Mirror the shared completion flag up to the wizard (immediate handles revisits
// where the profile is already complete).
watch(setupComplete, (v) => emit('update:complete', v), { immediate: true })

const profile = useCall({
  url: m(API.billingProfile),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})
const geo = useCall({ url: m(API.billingGeo) })

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
const countryOptions = computed(() => (geo.data?.countries ?? []).map((c) => ({ label: c, value: c })))
const stateOptions = computed(() => (geo.data?.india_states ?? []).map((s) => ({ label: s, value: s })))
// India drives the state dropdown — its value's GST code is what validates the GSTIN.
const isIndia = computed(() => form.country === 'India')

// Autocomplete works in {label, value} options; the profile stores plain strings,
// so proxy between the two.
function optionModel(field) {
  return computed({
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

const save = useCall({ url: m(API.saveBillingProfile), method: 'POST', immediate: false })
async function submit() {
  try {
    await save.submit({ team: currentTeam.value, ...form })
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
    <!-- Grouped into Currency / Contact / Address / Tax for hierarchy — mirrors the
         Settings billing profile. Once complete the fieldset disables every control
         and the Save action is hidden; edits happen later in Settings. -->
    <fieldset :disabled="complete" class="space-y-6">
      <div class="space-y-3">
        <h3 class="text-sm font-medium text-ink-gray-8">Billing currency</h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <FormControl
            type="select"
            v-model="form.currency"
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
            type="autocomplete"
            v-model="countryModel"
            label="Country *"
            placeholder="Select country"
            :options="countryOptions"
          />
          <FormControl
            v-if="isIndia"
            type="autocomplete"
            v-model="stateModel"
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
            :description="isIndia ? 'Its first two digits must match the selected state.' : ''"
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
