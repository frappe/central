<script setup lang="ts">
import { computed } from 'vue'
import { useCall, confirmDialog, Badge, Button, Dropdown, LoadingText } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { formatMoney } from '@/lib/plans'
import { successToast, errorToast } from '@/lib/toast'
import type { SubscriptionRow } from '@/types/billing'

// Subscriptions — the active per-server plan rows the invoice line items accrue
// from. Each row shows the server, its plan + region, and the monthly price; the
// kebab opens the server or pauses/resumes billing. Plan changes happen in the
// plan configurator.
const { subscriptions } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const rows = computed(() => subscriptions.data ?? [])

const pause = useCall<unknown, { subscription: string }>({
  url: method(API.pauseSubscription), method: 'POST', immediate: false,
})
const resume = useCall<unknown, { subscription: string }>({
  url: method(API.resumeSubscription), method: 'POST', immediate: false,
})
const busy = computed(() => pause.loading || resume.loading)

// Title falls back server → plan → id; the subtitle is "plan · region", skipping
// the plan when it is already serving as the title (a server with no friendly name).
function title(sub: SubscriptionRow): string {
  return sub.server || sub.plan_title || sub.name
}
function subtitle(sub: SubscriptionRow): string {
  const parts: string[] = []
  if (sub.plan_title && sub.plan_title !== title(sub)) parts.push(sub.plan_title)
  if (sub.region) parts.push(sub.region)
  return parts.join(' · ') || sub.billing_cycle || 'Monthly'
}
function price(sub: SubscriptionRow): string | null {
  return sub.monthly_rate != null ? `${formatMoney(sub.monthly_rate, sub.currency)}/mo` : null
}
function isPaused(sub: SubscriptionRow): boolean {
  return !sub.enabled
}

function pauseBilling(sub: SubscriptionRow): void {
  confirmDialog({
    title: 'Pause billing',
    message:
      `Pause billing for ${title(sub)}? This will stop the server/VM and the ` +
      `site(s)/services running on it, and stop charges until you resume.`,
    onConfirm: async ({ hideDialog }: { hideDialog: () => void }) => {
      try {
        await pause.submit({ subscription: sub.name })
        successToast('Billing paused; server stopping.')
        subscriptions.reload()
        hideDialog()
      } catch (e) {
        errorToast(e)
      }
    },
  })
}

async function resumeBilling(sub: SubscriptionRow): Promise<void> {
  try {
    await resume.submit({ subscription: sub.name })
    successToast('Billing resumed; server starting.')
    subscriptions.reload()
  } catch (e) {
    errorToast(e)
  }
}

function rowActions(sub: SubscriptionRow) {
  const actions: { label: string; icon: string; onClick: () => void }[] = []
  if (sub.gateway_url)
    actions.push({
      label: 'Open server',
      icon: 'lucide-external-link',
      onClick: () => window.open(sub.gateway_url!, '_blank', 'noopener'),
    })
  if (isPaused(sub))
    actions.push({ label: 'Resume billing', icon: 'lucide-play', onClick: () => resumeBilling(sub) })
  else
    actions.push({ label: 'Pause billing', icon: 'lucide-pause', onClick: () => pauseBilling(sub) })
  return actions
}
</script>

<template>
  <BillingCard title="Subscriptions">
    <div v-if="subscriptions.loading && !subscriptions.data" class="space-y-3">
      <LoadingText :lines="3" />
    </div>

    <div
      v-else-if="!rows.length"
      class="rounded border border-dashed border-outline-gray-2 px-6 py-8 text-center"
    >
      <p class="text-p-base text-ink-gray-6">No active subscriptions.</p>
    </div>

    <ul v-else class="divide-y divide-outline-gray-1">
      <li v-for="sub in rows" :key="sub.name" class="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
        <span class="lucide-server size-5 shrink-0 text-ink-gray-5" aria-hidden="true" />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <p class="truncate text-base font-medium text-ink-gray-8">{{ title(sub) }}</p>
            <Badge
              :theme="isPaused(sub) ? 'gray' : 'green'"
              :label="isPaused(sub) ? 'Paused' : 'Running'"
            />
          </div>
          <p class="truncate text-p-sm text-ink-gray-5">{{ subtitle(sub) }}</p>
        </div>
        <p v-if="price(sub)" class="shrink-0 text-base text-ink-gray-8" :class="{ 'text-ink-gray-4': isPaused(sub) }">
          {{ price(sub) }}
        </p>
        <Dropdown v-if="canManageBilling" :options="rowActions(sub)" placement="right">
          <Button variant="ghost" :loading="busy">
            <template #icon><span class="lucide-ellipsis size-4" aria-hidden="true" /></template>
          </Button>
        </Dropdown>
      </li>
    </ul>
  </BillingCard>
</template>
