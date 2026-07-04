<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCall, Badge, Button } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import PaymentMethodRowActions from '@/components/billing/PaymentMethodRowActions.vue'
import RemovePaymentMethodDialog from '@/components/billing/RemovePaymentMethodDialog.vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { successToast, errorToast } from '@/lib/toast'
import type { PaymentMethod } from '@/types/billing'

// Payment methods — primary + backups in fallback order, rendered as the FC v2
// prototype's clean divide-y list (rounded-square icon, Primary/Backup badge,
// ellipsis menu) rather than a table. The card owns the calls and the destructive
// remove confirm (a local Dialog, since this app mounts no global <Dialogs />
// container). Charges try the methods top-down; if one fails, billing falls back
// to the next.
const { activeTeam } = useSession()
const { methods, reloadMethods } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const ordered = computed(() => methods.data ?? [])
const loading = computed(() => methods.loading && !methods.data)

const setDefault = useCall<unknown, { payment_method: string }>({
  url: method(API.setDefaultPaymentMethod), method: 'POST', immediate: false,
})
const remove = useCall<unknown, { payment_method: string }>({
  url: method(API.removePaymentMethod), method: 'POST', immediate: false,
})
const reorder = useCall<unknown, { team: string; ordered: string[] }>({
  url: method(API.reorderPaymentMethods), method: 'POST', immediate: false,
})

// One row mutates at a time; `busy` holds its name so the row can show a spinner.
const busy = ref('')
const pendingRemove = ref<PaymentMethod | null>(null)

function methodIcon(pm: PaymentMethod): string {
  return pm.method_type === 'Card' ? 'lucide-credit-card' : 'lucide-smartphone'
}

// Row detail line: method type, expiry (cards), and the fallback rank so the
// top-down charge order stays legible.
function detail(pm: PaymentMethod, rank: number): string {
  const parts = [pm.method_type]
  if (pm.expiry_month && pm.expiry_year)
    parts.push(`expires ${String(pm.expiry_month).padStart(2, '0')}/${pm.expiry_year}`)
  if (ordered.value.length > 1) parts.push(`fallback #${rank}`)
  return parts.join(' · ')
}

async function makeDefault(pm: PaymentMethod): Promise<void> {
  busy.value = pm.name
  try {
    await setDefault.submit({ payment_method: pm.name })
    successToast('Default updated.')
    reloadMethods()
  } catch (e) {
    errorToast(e)
  } finally {
    busy.value = ''
  }
}

async function confirmRemove(pm: PaymentMethod): Promise<void> {
  busy.value = pm.name
  try {
    await remove.submit({ payment_method: pm.name })
    successToast('Payment method removed.')
    pendingRemove.value = null
    reloadMethods()
  } catch (e) {
    errorToast(e)
  } finally {
    busy.value = ''
  }
}

// Move a method up/down in the fallback order, then persist the whole order.
async function move(pm: PaymentMethod, delta: number): Promise<void> {
  const list = ordered.value.map((m) => m.name)
  const index = list.indexOf(pm.name)
  const target = index + delta
  if (index < 0 || target < 0 || target >= list.length) return
  ;[list[index], list[target]] = [list[target], list[index]]
  busy.value = pm.name
  try {
    await reorder.submit({ team: activeTeam.value!, ordered: list })
    reloadMethods()
  } catch (e) {
    errorToast(e)
  } finally {
    busy.value = ''
  }
}

const showAdd = ref(false)
function onAdd(): void {
  if (requireSetup()) showAdd.value = true
}
</script>

<template>
  <BillingCard
    title="Payment methods"
    title-info="The primary is charged first. If it fails, billing falls back to your next method."
  >
    <template #action>
      <Button
        v-if="canManageBilling"
        variant="ghost"
        icon="lucide-plus"
        :aria-label="ordered.length ? 'Add backup method' : 'Add payment method'"
        @click="onAdd"
      />
    </template>

    <div v-if="loading" class="space-y-3 py-1">
      <div v-for="i in 2" :key="i" class="flex items-center gap-3">
        <span class="size-8 shrink-0 animate-pulse rounded-lg bg-surface-gray-2" />
        <div class="flex-1 space-y-1.5">
          <span class="block h-3.5 w-32 animate-pulse rounded bg-surface-gray-2" />
          <span class="block h-3 w-24 animate-pulse rounded bg-surface-gray-2" />
        </div>
      </div>
    </div>

    <div v-else-if="ordered.length" class="divide-y divide-outline-gray-1">
      <div v-for="(pm, idx) in ordered" :key="pm.name" class="flex items-center gap-3 py-2.5">
        <span
          class="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-gray-2 text-ink-gray-6"
        >
          <span :class="methodIcon(pm)" class="size-4" aria-hidden="true" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-ink-gray-9">
            {{ pm.display_label || pm.method_type }}
          </p>
          <p class="truncate text-p-sm text-ink-gray-5">{{ detail(pm, idx + 1) }}</p>
        </div>
        <Badge v-if="pm.reauth_required" theme="orange" label="Re-auth needed" />
        <Badge v-else-if="pm.status !== 'Active'" theme="gray" :label="pm.status" />
        <Badge v-if="pm.is_default" theme="green" label="Primary" />
        <Badge v-else theme="gray" label="Backup" />
        <PaymentMethodRowActions
          :method="pm"
          :can-manage="canManageBilling"
          :is-first="idx === 0"
          :is-last="idx === ordered.length - 1"
          :busy="busy === pm.name"
          @make-default="makeDefault"
          @move-up="(m) => move(m, -1)"
          @move-down="(m) => move(m, 1)"
          @remove="pendingRemove = $event"
        />
      </div>
    </div>

    <EmptyState
      v-else
      icon="lucide-credit-card"
      title="No payment methods yet"
      description="Add a card or UPI Autopay so invoices can be charged automatically."
    >
      <template v-if="canManageBilling" #action>
        <Button variant="solid" theme="gray" label="Add payment method" @click="onAdd">
          <template #prefix><span class="lucide-plus size-4" aria-hidden="true" /></template>
        </Button>
      </template>
    </EmptyState>

    <RemovePaymentMethodDialog
      v-model:method="pendingRemove"
      :loading="busy === pendingRemove?.name"
      @confirm="confirmRemove"
    />
    <AddMethodDialog v-model="showAdd" @done="reloadMethods" />
  </BillingCard>
</template>
