<script setup>
import { reactive, watch } from 'vue'
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

// ── Billing profile (identity / address / GSTIN) ──
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
    successToast('Billing details saved.')
    profile.reload()
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Settings' }, { label: 'Address' }]" />

    <div class="body-container space-y-8 pb-40 pt-5">
      <div v-if="profile.loading && !profile.data" class="space-y-3">
        <LoadingText :lines="6" />
      </div>

      <section v-else class="space-y-4">
        <div>
          <h2 class="text-base text-ink-gray-9">Billing details</h2>
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
          label="Save details"
          :loading="saveProfile.loading"
          @click="submitProfile"
        />
      </section>
    </div>
  </div>
</template>
