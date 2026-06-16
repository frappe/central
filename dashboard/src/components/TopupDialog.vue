<script setup>
import { nextTick, ref, watch } from 'vue'
import { Dialog, Button, FormControl } from 'frappe-ui'
import { useTopup } from '@/composables/useTopup'
import { currencySymbol, money } from '@/utils/money'
import { errorToast } from '@/utils/toast'

// Amount entry → in-app payment. Shared by Overview and Credits.
// Razorpay (INR) collects in its hosted sheet; Stripe collects the card in an
// embedded Element right here (the address rides on the PaymentIntent from the
// billing profile — never re-asked). The wallet is credited only after the
// gateway confirms (see useTopup).
const props = defineProps({
  currency: { type: String, default: 'INR' },
})
const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['done'])

const amount = ref(null)
const presets = [1000, 5000, 10000, 25000]

// Stripe card phase: swap the amount field for the embedded card Element once a
// Stripe order is created and needs a card.
const cardPhase = ref(false)
const cardLoading = ref(false) // Stripe.js + Element still mounting
const cardEl = ref(null)

const { begin, mountCard, pay, destroy, cardComplete, submitting, loading } = useTopup({
  onDone: (res) => {
    open.value = false
    emit('done', res)
  },
})

async function submit() {
  const value = Number(amount.value)
  if (!value || value <= 0) return
  const { card } = await begin(value)
  if (!card) return // Razorpay finished in its sheet (or was cancelled/failed)

  cardPhase.value = true
  cardLoading.value = true
  await nextTick() // the Element needs its mount node in the DOM
  try {
    await mountCard(cardEl.value)
  } catch (e) {
    errorToast(e, 'Could not start secure card entry.')
    cardPhase.value = false
  } finally {
    cardLoading.value = false
  }
}

// Reset to the amount step whenever the dialog closes, tearing down any Element
// so a reopen never shows a stale card field.
watch(open, (isOpen) => {
  if (!isOpen) {
    destroy()
    amount.value = null
    cardPhase.value = false
    cardLoading.value = false
  }
})
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Top up wallet' }">
    <template #body-content>
      <!-- Stripe card entry: Element renders inside the iframe Stripe hosts. -->
      <div v-if="cardPhase" class="space-y-3">
        <p class="text-sm text-ink-gray-8">
          Paying {{ money(Number(amount), currency) }}
        </p>
        <p v-if="cardLoading" class="text-p-sm text-ink-gray-5">Loading secure card field…</p>
        <div ref="cardEl" class="rounded border border-outline-gray-2 px-3 py-3" />
        <p class="text-p-sm text-ink-gray-5">
          Card details are entered on Stripe’s secure field — we never see your card number.
          Your billing address is taken from your billing profile.
        </p>
      </div>

      <div v-else class="space-y-4">
        <div class="flex flex-wrap gap-2">
          <Button
            v-for="p in presets"
            :key="p"
            :label="`${currencySymbol(currency)}${p.toLocaleString()}`"
            :variant="Number(amount) === p ? 'solid' : 'subtle'"
            @click="amount = p"
          />
        </div>
        <FormControl
          v-model="amount"
          type="number"
          label="Amount"
          :placeholder="`Enter amount in ${currency}`"
          min="1"
        />
        <p class="text-p-sm text-ink-gray-5">
          You’ll complete payment securely. Your wallet is credited only after the
          payment is confirmed.
        </p>
      </div>
    </template>
    <template #actions>
      <Button
        v-if="cardPhase"
        variant="solid"
        :label="submitting ? 'Paying…' : 'Pay'"
        :loading="submitting"
        :disabled="!cardComplete"
        class="w-full"
        @click="pay"
      />
      <Button
        v-else
        variant="solid"
        label="Continue to payment"
        :loading="loading"
        :disabled="!amount || Number(amount) <= 0"
        class="w-full"
        @click="submit"
      />
    </template>
  </Dialog>
</template>
