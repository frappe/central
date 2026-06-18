<script setup>
import { computed, reactive, watch } from 'vue'
import { useCall } from 'frappe-ui'
import { Button, FormControl, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { successToast, errorToast } from '@/utils/toast'

const { currentTeam } = useTeam()
const { canManage } = useCapabilities()
const { complete, currencyLocked, supportedCurrencies, reload: reloadSetup } = useBillingSetup()

const params = () => ({ team: currentTeam.value })
const profile = useCall({ url: m(API.billingProfile), params, refetch: true })
const geo = useCall({ url: m(API.billingGeo) })

// ── Billing profile (currency / identity / address / tax) ──
// currency + legal name + a billing address are required before any money moves
// (top-up, credits, payment method); the picker offers only gateway-backed
// currencies and locks once the team has billing activity.
const PROFILE_FIELDS = [
  'currency', 'legal_name', 'email', 'phone', 'gstin',
  'address_line1', 'address_line2', 'city', 'state', 'country', 'pincode',
]
const form = reactive({})
watch(
  () => profile.data,
  (d) => {
    if (!d) return
    for (const f of PROFILE_FIELDS) form[f] = d[f] ?? ''
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

const saveProfile = useCall({ url: m(API.saveBillingProfile), method: 'POST', immediate: false })
async function submitProfile() {
  try {
    await saveProfile.submit({ team: currentTeam.value, ...form })
    successToast('Billing details saved.')
    profile.reload()
    reloadSetup()
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Settings' }, { label: 'Billing profile' }]">
      <template #actions>
        <Button
          v-if="canManage"
          variant="solid"
          label="Save"
          :loading="saveProfile.loading"
          @click="submitProfile"
        />
      </template>
    </PageHeader>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="body-container space-y-8 pb-40 pt-5">
        <div v-if="profile.loading && !profile.data" class="space-y-3">
          <LoadingText :lines="6" />
        </div>

        <section v-else class="space-y-8">
        <div>
          <h2 class="text-base text-ink-gray-9">Billing profile</h2>
          <p class="text-p-sm text-ink-gray-5">
            Set your billing currency and address before adding credits or a payment method.
            Appears on invoices; GSTIN drives tax treatment.
          </p>
        </div>

        <div
          v-if="!complete"
          class="rounded border border-outline-amber-2 bg-surface-amber-1 px-4 py-3 text-p-sm text-ink-amber-3"
        >
          Complete the required fields (marked *) to unlock top-ups, credits, and payment methods.
        </div>

        <!-- Currency -->
        <div class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Billing currency</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl
              type="select"
              v-model="form.currency"
              label="Billing currency *"
              :options="currencyOptions"
              :disabled="!canManage || currencyLocked"
            />
            <div class="flex items-end">
              <p v-if="currencyLocked" class="text-p-sm text-ink-gray-5">
                Currency is locked — your team already has billing activity.
              </p>
            </div>
          </div>
        </div>

        <!-- Contact -->
        <div class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Contact</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl v-model="form.legal_name" label="Legal name *" :disabled="!canManage" />
            <FormControl v-model="form.email" type="email" label="Billing email" :disabled="!canManage" />
            <FormControl v-model="form.phone" label="Phone" :disabled="!canManage" />
          </div>
        </div>

        <!-- Address -->
        <div class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Address</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl v-model="form.address_line1" label="Address line 1 *" :disabled="!canManage" />
            <FormControl v-model="form.address_line2" label="Address line 2" :disabled="!canManage" />
            <FormControl v-model="form.city" label="City *" :disabled="!canManage" />
            <FormControl
              type="autocomplete"
              v-model="countryModel"
              label="Country *"
              placeholder="Select country"
              :options="countryOptions"
              :disabled="!canManage"
            />
            <FormControl
              v-if="isIndia"
              type="autocomplete"
              v-model="stateModel"
              label="State *"
              placeholder="Select state"
              :options="stateOptions"
              :disabled="!canManage"
            />
            <FormControl v-else v-model="form.state" label="State *" :disabled="!canManage" />
            <FormControl v-model="form.pincode" label="PIN code *" :disabled="!canManage" />
          </div>
        </div>

        <!-- Tax details — GSTIN is India-only. -->
        <div v-if="isIndia" class="space-y-3">
          <h3 class="text-sm font-medium text-ink-gray-8">Tax details</h3>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl
              v-model="form.gstin"
              label="GSTIN"
              :disabled="!canManage"
              description="Its first two digits must match the selected state."
            />
          </div>
        </div>
        </section>
      </div>
    </div>
  </div>
</template>
