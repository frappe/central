<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Dialog, Button, FormControl } from 'frappe-ui'
import { useTopup } from '@/composables/useTopup'
import { currencySymbol, money } from '@/utils/money'
import { errorToast } from '@/utils/toast'

// Amount entry → in-app payment. Shared by Overview and Credits.
// Razorpay (INR) collects in its hosted sheet; Stripe collects the card in an
// embedded Element right here; PayPal renders its Buttons in a second phase. The
// wallet is credited only after the gateway confirms (see useTopup).
const props = defineProps({
  currency: { type: String, default: 'INR' },
})
const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['done'])

const amount = ref(null)
const presets = [1000, 5000, 10000, 25000]

// Payment rail. INR always uses the Razorpay sheet; international currencies pick
// between a card (Stripe Element) and PayPal (directly settled, ADR 0007).
const method = ref('card') // 'card' | 'paypal'
const showMethodChoice = computed(() => props.currency !== 'INR')

// Second-phase mount targets: Stripe card Element / PayPal Buttons.
const cardPhase = ref(false)
const cardLoading = ref(false) // Stripe.js + Element still mounting
const cardEl = ref(null)
const paypalPhase = ref(false)
const paypalLoading = ref(false) // PayPal SDK + Buttons still mounting
const paypalEl = ref(null)

const { begin, mountCard, mountPayPal, pay, destroy, cardComplete, submitting, loading } = useTopup({
  onDone: (res) => {
    open.value = false
    emit('done', res)
  },
})

async function submit() {
  const value = Number(amount.value)
  if (!value || value <= 0) return
  // PayPal is only offered for international currencies; INR stays on the default rail.
  const chosen = showMethodChoice.value && method.value === 'paypal' ? 'paypal' : undefined
  const { card, paypal } = await begin(value, chosen)
  if (paypal) return enterPhase(paypalPhase, paypalLoading, paypalEl, mountPayPal, 'Could not start PayPal.')
  if (card) return enterPhase(cardPhase, cardLoading, cardEl, mountCard, 'Could not start secure card entry.')
  // else: Razorpay finished in its sheet (or was cancelled/failed) — nothing to mount.
}

// Switch to a second-phase view and mount its gateway widget into the fresh node.
async function enterPhase(phase, loadingRef, elRef, mount, failMsg) {
  phase.value = true
  loadingRef.value = true
  await nextTick() // the widget needs its mount node in the DOM
  try {
    await mount(elRef.value)
  } catch (e) {
    errorToast(e, failMsg)
    phase.value = false
  } finally {
    loadingRef.value = false
  }
}

// Reset to the amount step whenever the dialog closes, tearing down any widget so
// a reopen never shows a stale card field / buttons.
watch(open, (isOpen) => {
  if (!isOpen) {
    destroy()
    amount.value = null
    method.value = 'card'
    cardPhase.value = false
    cardLoading.value = false
    paypalPhase.value = false
    paypalLoading.value = false
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

      <!-- PayPal entry: PayPal Buttons render here; approval happens in PayPal's popup. -->
      <div v-else-if="paypalPhase" class="space-y-3">
        <p class="text-sm text-ink-gray-8">
          Paying {{ money(Number(amount), currency) }}
        </p>
        <p v-if="paypalLoading" class="text-p-sm text-ink-gray-5">Loading PayPal…</p>
        <div ref="paypalEl" />
        <p class="text-p-sm text-ink-gray-5">
          You’ll approve the payment in PayPal. Your wallet is credited only after PayPal confirms.
        </p>
      </div>

      <div v-else class="space-y-5">
        <div v-if="showMethodChoice">
          <p class="mb-1.5 text-p-sm text-ink-gray-5">Pay with</p>
          <div class="flex gap-2">
            <Button
              label="Card"
              :variant="method === 'card' ? 'solid' : 'subtle'"
              @click="method = 'card'"
            />
            <Button
              label="PayPal"
              :variant="method === 'paypal' ? 'solid' : 'subtle'"
              @click="method = 'paypal'"
            />
          </div>
        </div>
        <div>
          <p class="mb-1.5 text-p-sm text-ink-gray-5">Amount</p>
          <div class="mb-2 flex flex-wrap gap-2">
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
            :placeholder="`Enter amount in ${currency}`"
            min="1"
          />
        </div>
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
      <!-- PayPal phase: the PayPal Buttons are the action; no footer button. -->
      <Button
        v-else-if="!paypalPhase"
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
