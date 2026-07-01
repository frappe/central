<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import SubscriptionsListView from '@/components/billing/SubscriptionsListView.vue'
import PauseBillingDialog from '@/components/billing/PauseBillingDialog.vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast, errorToast } from '@/lib/toast'
import type { SubscriptionRow } from '@/types/billing'

// Subscriptions — the active per-server plan rows the invoice line items accrue
// from, rendered with the same ListView the server list uses. The card owns the
// pause/resume calls and the destructive-style pause confirm (a local Dialog, since
// this app mounts no global <Dialogs /> container). Pause stops the linked VM.
const { subscriptions } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const rows = computed(() => subscriptions.data ?? [])

const pause = useCall<unknown, { subscription: string }>({
  url: method(API.pauseSubscription), method: 'POST', immediate: false,
})
const resume = useCall<unknown, { subscription: string }>({
  url: method(API.resumeSubscription), method: 'POST', immediate: false,
})

// One row mutates at a time; `busy` holds its name so the row can show a spinner.
const busy = ref('')
const pendingPause = ref<SubscriptionRow | null>(null)

function onPause(sub: SubscriptionRow): void {
  pendingPause.value = sub
}

async function confirmPause(sub: SubscriptionRow): Promise<void> {
  pendingPause.value = null
  busy.value = sub.name
  try {
    await pause.submit({ subscription: sub.name })
    successToast('Billing paused; server stopping.')
    subscriptions.reload()
  } catch (e) {
    errorToast(e)
  } finally {
    busy.value = ''
  }
}

async function onResume(sub: SubscriptionRow): Promise<void> {
  busy.value = sub.name
  try {
    await resume.submit({ subscription: sub.name })
    successToast('Billing resumed; server starting.')
    subscriptions.reload()
  } catch (e) {
    errorToast(e)
  } finally {
    busy.value = ''
  }
}

function onOpen(sub: SubscriptionRow): void {
  if (sub.gateway_url) window.open(sub.gateway_url, '_blank', 'noopener')
}
</script>

<template>
  <BillingCard title="Subscriptions">
    <SubscriptionsListView
      :subscriptions="rows"
      :loading="subscriptions.loading && !subscriptions.data"
      :can-manage="canManageBilling"
      :busy="busy"
      @open="onOpen"
      @pause="onPause"
      @resume="onResume"
    />
    <PauseBillingDialog
      v-model:subscription="pendingPause"
      :loading="busy === pendingPause?.name"
      @confirm="confirmPause"
    />
  </BillingCard>
</template>
