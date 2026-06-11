<script setup>
import { reactive, watch, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { Button, FormControl, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast, errorToast } from '@/utils/toast'

const { currentTeam } = useTeam()
const { canManage } = useCapabilities()

const params = () => ({ team: currentTeam.value })
const profile = useCall({ url: m(API.billingProfile), params, refetch: true })
const settings = useCall({ url: m(API.billingSettings), params, refetch: true })

// ── Billing profile (identity / GSTIN) ──
const PROFILE_FIELDS = [
  'legal_name', 'email', 'phone', 'gstin',
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

const saveProfile = useCall({ url: m(API.saveBillingProfile), immediate: false })
async function submitProfile() {
  try {
    await saveProfile.submit({ team: currentTeam.value, ...form })
    successToast('Billing profile saved.')
    profile.reload()
  } catch (e) {
    errorToast(e)
  }
}

// ── Billing settings (mode + thresholds) ──
const mode = ref('Postpaid')
const minBalance = ref(0)
const spendAlert = ref(0)
watch(
  () => settings.data,
  (d) => {
    if (!d) return
    mode.value = d.billing_mode || 'Postpaid'
    minBalance.value = d.min_balance ?? 0
    spendAlert.value = d.spend_alert_threshold ?? 0
  },
  { immediate: true },
)

const saveSettings = useCall({ url: m(API.saveBillingSettings), immediate: false })
async function submitSettings() {
  try {
    await saveSettings.submit({
      team: currentTeam.value,
      billing_mode: mode.value,
      min_balance: minBalance.value,
      spend_alert_threshold: spendAlert.value,
    })
    successToast('Settings saved — mode changes apply next billing period.')
    settings.reload()
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Billing' }, { label: 'Settings' }]" />

    <div class="body-container space-y-8 pb-40 pt-5">
      <div v-if="profile.loading && !profile.data" class="space-y-3">
        <LoadingText :lines="6" />
      </div>

      <template v-else>
        <!-- Billing profile -->
        <section class="space-y-4">
          <div>
            <h2 class="text-base text-ink-gray-9">Billing profile</h2>
            <p class="text-p-sm text-ink-gray-5">Appears on invoices; GSTIN drives tax treatment.</p>
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl v-model="form.legal_name" label="Legal name" :disabled="!canManage" />
            <FormControl v-model="form.gstin" label="GSTIN" :disabled="!canManage" />
            <FormControl v-model="form.email" type="email" label="Billing email" :disabled="!canManage" />
            <FormControl v-model="form.phone" label="Phone" :disabled="!canManage" />
            <FormControl v-model="form.address_line1" label="Address line 1" :disabled="!canManage" />
            <FormControl v-model="form.address_line2" label="Address line 2" :disabled="!canManage" />
            <FormControl v-model="form.city" label="City" :disabled="!canManage" />
            <FormControl v-model="form.state" label="State" :disabled="!canManage" />
            <FormControl v-model="form.country" label="Country" :disabled="!canManage" />
            <FormControl v-model="form.pincode" label="PIN code" :disabled="!canManage" />
          </div>
          <Button
            v-if="canManage"
            variant="solid"
            label="Save profile"
            :loading="saveProfile.loading"
            @click="submitProfile"
          />
        </section>

        <!-- Billing settings -->
        <section class="space-y-4 border-t border-outline-gray-1 pt-8">
          <div>
            <h2 class="text-base text-ink-gray-9">Payment mode</h2>
            <p class="text-p-sm text-ink-gray-5">
              Postpaid bills at month-end; Prepaid draws from your wallet. Changes apply next period.
            </p>
          </div>
          <FormControl
            v-model="mode"
            type="select"
            label="Mode"
            :options="['Postpaid', 'Prepaid']"
            :disabled="!canManage"
          />
          <div class="grid gap-4 sm:grid-cols-2">
            <FormControl
              v-model="minBalance"
              type="number"
              label="Minimum wallet balance"
              :disabled="!canManage"
            />
            <FormControl
              v-model="spendAlert"
              type="number"
              label="Spend alert threshold"
              :disabled="!canManage"
            />
          </div>
          <Button
            v-if="canManage"
            variant="solid"
            label="Save settings"
            :loading="saveSettings.loading"
            @click="submitSettings"
          />
        </section>
      </template>
    </div>
  </div>
</template>
