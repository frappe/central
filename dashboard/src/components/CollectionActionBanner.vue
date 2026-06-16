<script setup>
// "Action Required" banner — shown when an INR e-mandate team's bill crosses the
// ₹15,000 silent-debit limit and the customer must choose how to keep paying
// (ADR 0005 / payments-inr.md). Calm, not alarming: services keep running; this is
// an invitation to decide. First-pass UI — the design team refines from the brief
// (docs/design/inr-collection-action-required.md). Backend feed: get_collection_status.
import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { Dialog, Button } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { money } from '@/utils/money'
import { successToast, errorToast } from '@/utils/toast'

const { currentTeam } = useTeam()
const { canManage } = useCapabilities()

const params = () => ({ team: currentTeam.value })
const status = useCall({ url: m(API.collectionStatus), params, refetch: true })

const s = computed(() => status.data || {})
const show = computed(() => !!s.value.action_required)
const currency = computed(() => s.value.currency || 'INR')

const choosing = ref(false)
const chosen = ref(null) // 'manual_checkout' | 'prepaid'

const setMode = useCall({
  url: m(API.setCollectionMode),
  method: 'POST',
  immediate: false,
  onError: (e) => errorToast(e, 'Could not update how you pay.'),
})

async function choose() {
  if (!chosen.value) return
  await setMode.submit({ team: currentTeam.value, mode: chosen.value })
  successToast(
    chosen.value === 'prepaid'
      ? 'Switched to prepaid wallet. Add credits to cover your usage.'
      : 'You’ll now pay each invoice yourself.',
  )
  choosing.value = false
  chosen.value = null
  status.reload()
}

const options = [
  {
    key: 'manual_checkout',
    icon: 'lucide-receipt',
    title: 'Pay each invoice',
    blurb: 'We email you each bill; you pay in a few taps (any amount).',
    fit: 'Best if your usage varies a lot month to month.',
  },
  {
    key: 'prepaid',
    icon: 'lucide-wallet',
    title: 'Prepaid wallet',
    blurb: 'Add credits up front; your usage draws them down.',
    fit: 'Best for hands-off, predictable spending.',
  },
]
</script>

<template>
  <div
    v-if="show"
    class="flex flex-col gap-3 rounded-lg border border-outline-amber-1 bg-surface-amber-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
    role="status"
    aria-live="polite"
  >
    <div class="flex items-start gap-3">
      <span class="lucide-triangle-alert mt-0.5 size-5 shrink-0 text-ink-amber-3" aria-hidden="true" />
      <div class="space-y-0.5">
        <p class="text-base font-medium text-ink-gray-9">Action required — choose how to keep paying</p>
        <p class="text-p-sm text-ink-gray-7">
          Your usage is trending to
          <span class="font-medium">{{ money(s.projected_total, currency) }}</span>
          this month, above the
          <span class="font-medium">{{ money(s.threshold, currency) }}</span>
          limit for automatic payments. Your services keep running.
        </p>
      </div>
    </div>
    <Button
      v-if="canManage"
      variant="solid"
      theme="gray"
      label="Choose how to pay"
      class="shrink-0"
      @click="choosing = true"
    />
  </div>

  <Dialog v-model="choosing" :options="{ title: 'How would you like to pay going forward?' }">
    <template #body-content>
      <div class="grid gap-3 sm:grid-cols-2">
        <button
          v-for="o in options"
          :key="o.key"
          type="button"
          class="flex flex-col gap-2 rounded-lg border p-4 text-left transition-colors"
          :class="
            chosen === o.key
              ? 'border-outline-gray-4 bg-surface-gray-2'
              : 'border-outline-gray-2 hover:border-outline-gray-3'
          "
          @click="chosen = o.key"
        >
          <span :class="o.icon" class="size-5 text-ink-gray-7" aria-hidden="true" />
          <span class="text-base font-medium text-ink-gray-9">{{ o.title }}</span>
          <span class="text-p-sm text-ink-gray-6">{{ o.blurb }}</span>
          <span class="mt-auto text-p-sm text-ink-gray-5">{{ o.fit }}</span>
        </button>
      </div>
      <p class="mt-3 text-p-sm text-ink-gray-5">You can switch anytime in Billing settings.</p>
    </template>
    <template #actions>
      <Button
        variant="solid"
        label="Confirm"
        class="w-full"
        :loading="setMode.loading"
        :disabled="!chosen"
        @click="choose"
      />
    </template>
  </Dialog>
</template>
