<script setup lang="ts">
import { computed } from 'vue'
import { Button, LoadingText } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'

// Billing contact — the email + address invoices are addressed to. Edit opens the
// shared profile dialog (owned by the page).
defineEmits<{ edit: [] }>()
const { profile } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const loading = computed(() => profile.loading && !profile.data)
const email = computed(() => profile.data?.email || '')
const legalName = computed(() => profile.data?.legal_name || '')
const address = computed(() => {
  const p = profile.data
  if (!p) return ''
  return [p.address_line1, p.address_line2, p.city, p.state, p.country, p.pincode]
    .filter(Boolean)
    .join(', ')
})
</script>

<template>
  <BillingCard title="Billing contact">
    <template #action>
      <Button
        v-if="canManageBilling"
        variant="ghost"
        icon="lucide-pencil"
        aria-label="Edit billing contact"
        @click="$emit('edit')"
      />
    </template>

    <div v-if="loading" class="space-y-3">
      <LoadingText :lines="3" />
    </div>

    <dl v-else class="space-y-3 text-sm">
      <div class="flex justify-between gap-3">
        <dt class="text-ink-gray-5">Legal name</dt>
        <dd class="text-right" :class="legalName ? 'text-ink-gray-8' : 'text-ink-gray-5'">
          {{ legalName || 'Not set' }}
        </dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="text-ink-gray-5">Email</dt>
        <dd class="truncate text-right" :class="email ? 'text-ink-gray-8' : 'text-ink-gray-5'">
          {{ email || 'Not set' }}
        </dd>
      </div>
      <div class="flex justify-between gap-3">
        <dt class="shrink-0 text-ink-gray-5">Address</dt>
        <dd class="text-right" :class="address ? 'text-ink-gray-8' : 'text-ink-gray-5'">
          {{ address || 'No address on file' }}
        </dd>
      </div>
    </dl>
  </BillingCard>
</template>
