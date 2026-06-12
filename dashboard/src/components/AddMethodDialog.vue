<script setup>
import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { Dialog, Button, FormControl, LoadingText } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useAddPaymentMethod } from '@/composables/useAddPaymentMethod'
import { money } from '@/utils/money'

// Pick a method to add, resolved from the team's billing currency. UPI Autopay
// is offered only when eligible (recurring-limit/trust gate from the backend).
const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['done'])
const { currentTeam } = useTeam()

const params = () => ({ team: currentTeam.value })
const options = useCall({ url: m(API.paymentMethodOptions), params, refetch: true })
const profile = useCall({ url: m(API.billingProfile), params, refetch: true })

const { run, loading } = useAddPaymentMethod({
  onDone: (res) => {
    open.value = false
    emit('done', res)
  },
})

const upiBlocked = computed(() => options.data && !options.data.allow_upi)

// A Razorpay card mandate needs a customer contact; phone is optional on the
// profile, so collect it inline here when it's missing.
const cardNeedsPhone = computed(
  () => options.data?.adapter_key === 'Razorpay' && !String(profile.data?.phone || '').trim(),
)
const askPhone = ref(false)
const phone = ref('')

function onCard() {
  if (cardNeedsPhone.value && !phone.value.trim()) {
    askPhone.value = true
    return
  }
  run('Card', phone.value.trim() || undefined)
}
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
          @click="onCard"
        >
          <div>
            <p class="text-sm text-ink-gray-8">Card</p>
            <p class="text-p-sm text-ink-gray-5">
              Saved securely with {{ options.data.adapter_key }} · {{ options.data.currency }}
            </p>
          </div>
          <span class="lucide-credit-card size-5 text-ink-gray-5" />
        </button>

        <div v-if="askPhone" class="space-y-2 rounded border border-outline-gray-2 px-4 py-3">
          <FormControl
            v-model="phone"
            type="text"
            label="Phone number"
            placeholder="Mobile number"
            description="Razorpay requires a contact for recurring card payments. Saved to your billing profile."
          />
          <Button
            variant="solid"
            label="Continue"
            :loading="loading"
            :disabled="!phone.trim()"
            @click="run('Card', phone.trim())"
          />
        </div>

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
