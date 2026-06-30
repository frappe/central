<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCall, Button } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import PaymentMethodsListView from '@/components/billing/PaymentMethodsListView.vue'
import RemovePaymentMethodDialog from '@/components/billing/RemovePaymentMethodDialog.vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { successToast, errorToast } from '@/lib/toast'
import type { PaymentMethod } from '@/types/billing'

// Payment methods — primary + backups in fallback order; add / make-default /
// reorder / remove, rendered with the same ListView the rest of billing uses. The
// card owns the calls and the destructive remove confirm (a local Dialog, since
// this app mounts no global <Dialogs /> container). Charges try the methods
// top-down; if one fails, billing falls back to the next.
const { activeTeam } = useSession()
const { methods, reloadMethods } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const ordered = computed(() => methods.data ?? [])

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
  <BillingCard title="Payment methods">
    <template #action>
      <Button v-if="canManageBilling" variant="subtle" label="Add method" @click="onAdd" />
    </template>

    <PaymentMethodsListView
      :methods="ordered"
      :loading="methods.loading && !methods.data"
      :can-manage="canManageBilling"
      :busy="busy"
      @make-default="makeDefault"
      @move-up="(pm) => move(pm, -1)"
      @move-down="(pm) => move(pm, 1)"
      @remove="pendingRemove = $event"
    />

    <p v-if="ordered.length > 1" class="mt-3 text-p-sm text-ink-gray-5">
      Charges try the methods top-down; if one fails, billing falls back to the next.
    </p>

    <RemovePaymentMethodDialog
      v-model:method="pendingRemove"
      :loading="busy === pendingRemove?.name"
      @confirm="confirmRemove"
    />
    <AddMethodDialog v-model="showAdd" @done="reloadMethods" />
  </BillingCard>
</template>
