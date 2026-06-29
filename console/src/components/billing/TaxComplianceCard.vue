<script setup lang="ts">
import { computed } from 'vue'
import { Button, Badge, LoadingText } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'

// Tax & compliance — billing region (country) + GSTIN, which drives tax treatment.
// Edit opens the shared profile dialog (owned by the page).
defineEmits<{ edit: [] }>()
const { profile } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const loading = computed(() => profile.loading && !profile.data)
const country = computed(() => profile.data?.country || '')
const state = computed(() => profile.data?.state || '')
const gstin = computed(() => profile.data?.gstin || '')
const isIndia = computed(() => country.value === 'India')
</script>

<template>
  <BillingCard title="Tax & compliance">
    <template #action>
      <Button
        v-if="canManageBilling"
        variant="ghost"
        icon="lucide-pencil"
        aria-label="Edit tax details"
        @click="$emit('edit')"
      />
    </template>

    <div v-if="loading" class="space-y-3">
      <LoadingText :lines="2" />
    </div>

    <dl v-else class="space-y-3 text-sm">
      <div class="flex justify-between gap-3">
        <dt class="text-ink-gray-5">Region</dt>
        <dd class="text-right" :class="country ? 'text-ink-gray-8' : 'text-ink-gray-5'">
          {{ [state, country].filter(Boolean).join(', ') || 'Not set' }}
        </dd>
      </div>
      <div v-if="isIndia" class="flex items-center justify-between gap-3">
        <dt class="text-ink-gray-5">GSTIN</dt>
        <dd v-if="gstin" class="text-right font-mono text-ink-gray-8">{{ gstin }}</dd>
        <Badge v-else theme="gray" label="Not provided" />
      </div>
    </dl>
  </BillingCard>
</template>
