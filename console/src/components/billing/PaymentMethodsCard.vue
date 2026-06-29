<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCall, confirmDialog, Badge, Button, Dropdown, LoadingText } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { successToast, errorToast } from '@/lib/toast'
import type { PaymentMethod } from '@/types/billing'

// Payment methods — primary + backups in fallback order; add / make-default /
// reorder / remove. Charges try the methods top-down; if one fails, billing falls
// back to the next.
const { activeTeam } = useSession()
const { methods, reloadMethods } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const ordered = computed(() => methods.data ?? [])

const setDefault = useCall<unknown, { payment_method: string }>({
  url: method(API.setDefaultPaymentMethod), immediate: false,
})
const remove = useCall<unknown, { payment_method: string }>({
  url: method(API.removePaymentMethod), immediate: false,
})
const reorder = useCall<unknown, { team: string; ordered: string[] }>({
  url: method(API.reorderPaymentMethods), immediate: false,
})

async function makeDefault(pm: PaymentMethod): Promise<void> {
  try {
    await setDefault.submit({ payment_method: pm.name })
    successToast('Default updated.')
    reloadMethods()
  } catch (e) {
    errorToast(e)
  }
}

function removeMethod(pm: PaymentMethod): void {
  const label = pm.display_label || pm.name
  confirmDialog({
    title: 'Remove payment method',
    message: `Remove ${label}? Invoices will fall back to your other methods, if any.`,
    onConfirm: async ({ hideDialog }: { hideDialog: () => void }) => {
      try {
        await remove.submit({ payment_method: pm.name })
        successToast('Payment method removed.')
        reloadMethods()
        hideDialog()
      } catch (e) {
        errorToast(e)
      }
    },
  })
}

// Move a method up/down in the fallback order, then persist the whole order.
async function move(index: number, delta: number): Promise<void> {
  const list = ordered.value.map((m) => m.name)
  const target = index + delta
  if (target < 0 || target >= list.length) return
  ;[list[index], list[target]] = [list[target], list[index]]
  try {
    await reorder.submit({ team: activeTeam.value!, ordered: list })
    reloadMethods()
  } catch (e) {
    errorToast(e)
  }
}

const busy = computed(() => setDefault.loading || remove.loading || reorder.loading)

function rowActions(pm: PaymentMethod, index: number) {
  const actions: { label: string; onClick: () => void }[] = []
  if (!pm.is_default) actions.push({ label: 'Make default', onClick: () => makeDefault(pm) })
  if (index > 0) actions.push({ label: 'Move up', onClick: () => move(index, -1) })
  if (index < ordered.value.length - 1)
    actions.push({ label: 'Move down', onClick: () => move(index, 1) })
  actions.push({ label: 'Remove', onClick: () => removeMethod(pm) })
  return actions
}

const showAdd = ref(false)
function onAdd(): void {
  if (requireSetup()) showAdd.value = true
}

function methodIcon(type: string): string {
  return type === 'Card' ? 'lucide-credit-card' : 'lucide-smartphone'
}
</script>

<template>
  <BillingCard title="Payment methods">
    <template #action>
      <Button v-if="canManageBilling" variant="subtle" label="Add method" @click="onAdd" />
    </template>

    <div v-if="methods.loading && !methods.data" class="space-y-3">
      <LoadingText :lines="3" />
    </div>

    <div
      v-else-if="!ordered.length"
      class="rounded border border-dashed border-outline-gray-2 px-6 py-8 text-center"
    >
      <p class="text-p-base text-ink-gray-6">No payment methods yet.</p>
      <p class="mt-1 text-p-sm text-ink-gray-5">
        Add a card or UPI Autopay so invoices can be charged automatically.
      </p>
    </div>

    <template v-else>
      <ul class="space-y-2">
        <li
          v-for="(pm, index) in ordered"
          :key="pm.name"
          class="flex items-center gap-3 rounded border border-outline-gray-1 px-4 py-3"
        >
          <span :class="[methodIcon(pm.method_type), 'size-5 text-ink-gray-5']" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="truncate text-sm text-ink-gray-8">
                {{ pm.display_label || pm.method_type }}
              </p>
              <Badge v-if="pm.is_default" theme="green" label="Default" />
              <Badge v-if="pm.reauth_required" theme="orange" label="Re-auth needed" />
              <Badge v-if="pm.status !== 'Active'" theme="gray" :label="pm.status" />
            </div>
            <p class="text-p-sm text-ink-gray-5">
              {{ pm.method_type }}
              <span v-if="pm.expiry_month && pm.expiry_year">
                · expires {{ String(pm.expiry_month).padStart(2, '0') }}/{{ pm.expiry_year }}
              </span>
              · fallback #{{ index + 1 }}
            </p>
          </div>
          <Dropdown v-if="canManageBilling" :options="rowActions(pm, index)" placement="right">
            <Button variant="ghost" :loading="busy">
              <template #icon><span class="lucide-ellipsis size-4" aria-hidden="true" /></template>
            </Button>
          </Dropdown>
        </li>
      </ul>

      <p v-if="ordered.length > 1" class="mt-3 text-p-sm text-ink-gray-5">
        Charges try the methods top-down; if one fails, billing falls back to the next.
      </p>
    </template>

    <AddMethodDialog v-model="showAdd" @done="reloadMethods" />
  </BillingCard>
</template>
