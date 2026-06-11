<script setup>
import { ref } from 'vue'
import { Dialog, Button, FormControl } from 'frappe-ui'
import { useTopup } from '@/composables/useTopup'
import { currencySymbol } from '@/utils/money'

// Amount entry → gateway checkout. Shared by Overview and Credits.
// The wallet is credited only after the gateway confirms (see useTopup).
const props = defineProps({
  currency: { type: String, default: 'INR' },
})
const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['done'])

const amount = ref(null)
const presets = [1000, 5000, 10000, 25000]

const { run, loading } = useTopup({
  onDone: (res) => {
    open.value = false
    amount.value = null
    emit('done', res)
  },
})

async function submit() {
  const value = Number(amount.value)
  if (!value || value <= 0) return
  await run(value)
}
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Top up wallet' }">
    <template #body-content>
      <div class="space-y-4">
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
          You’ll complete payment on the gateway’s secure checkout. Your wallet is
          credited only after the payment is confirmed.
        </p>
      </div>
    </template>
    <template #actions>
      <Button
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
