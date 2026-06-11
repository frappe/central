<script setup>
import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { Dialog, Button, LoadingText } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useAddPaymentMethod } from '@/composables/useAddPaymentMethod'
import { money } from '@/utils/money'

// Pick a method to add, resolved from the team's billing currency. UPI Autopay
// is offered only when eligible (recurring-limit/trust gate from the backend).
const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['done'])
const { currentTeam } = useTeam()

const options = useCall({
  url: m(API.paymentMethodOptions),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

const { run, loading } = useAddPaymentMethod({
  onDone: (res) => {
    open.value = false
    emit('done', res)
  },
})

const upiBlocked = computed(() => options.data && !options.data.allow_upi)
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Add payment method' }">
    <template #body-content>
      <div v-if="options.loading && !options.data" class="space-y-2">
        <LoadingText :lines="3" />
      </div>
      <div v-else-if="options.data" class="space-y-3">
        <button
          v-if="options.data.methods.includes('Card')"
          class="flex w-full items-center justify-between rounded border border-outline-gray-2 px-4 py-3 text-left hover:border-outline-gray-3 disabled:opacity-50"
          :disabled="loading"
          @click="run('Card')"
        >
          <div>
            <p class="text-sm text-ink-gray-8">Card</p>
            <p class="text-p-sm text-ink-gray-5">
              Saved securely with {{ options.data.adapter_key }} · {{ options.data.currency }}
            </p>
          </div>
          <span class="lucide-credit-card size-5 text-ink-gray-5" />
        </button>

        <button
          v-if="options.data.methods.includes('UPI Autopay')"
          class="flex w-full items-center justify-between rounded border border-outline-gray-2 px-4 py-3 text-left hover:border-outline-gray-3 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="loading || upiBlocked"
          @click="run('UPI Autopay')"
        >
          <div>
            <p class="text-sm text-ink-gray-8">UPI Autopay</p>
            <p v-if="upiBlocked" class="text-p-sm text-ink-amber-3">
              {{ options.data.upi_block_reason || 'Not available for your account yet.' }}
            </p>
            <p v-else class="text-p-sm text-ink-gray-5">
              Recurring mandate up to {{ money(options.data.upi_limit, options.data.currency) }}
            </p>
          </div>
          <span class="lucide-smartphone size-5 text-ink-gray-5" />
        </button>

        <p class="text-p-sm text-ink-gray-5">
          You’ll authorise the method on {{ options.data.adapter_key }}’s secure sheet. We never
          see your card or UPI credentials.
        </p>
      </div>
    </template>
  </Dialog>
</template>
