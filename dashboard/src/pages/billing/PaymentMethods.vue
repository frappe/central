<script setup>
import { computed, ref } from 'vue'
import { useCall } from 'frappe-ui'
import { Badge, Button, Dropdown, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/PageHeader.vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast, errorToast } from '@/utils/toast'

const { currentTeam } = useTeam()
const { canManage } = useCapabilities()

const methods = useCall({
  url: m(API.paymentMethods),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})

// Methods come back already in fallback order (priority asc). The team's charge
// order is primary → backups; reorder pushes a new top-first list to the server.
const ordered = computed(() => methods.data || [])

const setDefault = useCall({ url: m(API.setDefaultPaymentMethod), method: 'POST', immediate: false })
const remove = useCall({ url: m(API.removePaymentMethod), method: 'POST', immediate: false })
const reorder = useCall({ url: m(API.reorderPaymentMethods), method: 'POST', immediate: false })

async function makeDefault(pm) {
  try {
    await setDefault.submit({ payment_method: pm.name })
    successToast('Default updated.')
    methods.reload()
  } catch (e) {
    errorToast(e)
  }
}

async function removeMethod(pm) {
  try {
    await remove.submit({ payment_method: pm.name })
    successToast('Payment method removed.')
    methods.reload()
  } catch (e) {
    errorToast(e)
  }
}

// Move a method up/down in the fallback order, then persist the whole order.
async function move(index, delta) {
  const list = ordered.value.map((m) => m.name)
  const target = index + delta
  if (target < 0 || target >= list.length) return
  ;[list[index], list[target]] = [list[target], list[index]]
  try {
    await reorder.submit({ team: currentTeam.value, ordered: list })
    methods.reload()
  } catch (e) {
    errorToast(e)
  }
}

const busy = computed(() => setDefault.loading || remove.loading || reorder.loading)

function rowActions(pm, index) {
  const actions = []
  if (!pm.is_default) {
    actions.push({ label: 'Make default', onClick: () => makeDefault(pm) })
  }
  if (index > 0) actions.push({ label: 'Move up', onClick: () => move(index, -1) })
  if (index < ordered.value.length - 1) actions.push({ label: 'Move down', onClick: () => move(index, 1) })
  actions.push({ label: 'Remove', onClick: () => removeMethod(pm) })
  return actions
}

const showAdd = ref(false)

function methodIcon(type) {
  return type === 'Card' ? 'lucide-credit-card' : 'lucide-smartphone'
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader :items="[{ label: 'Settings' }, { label: 'Payment Methods' }]">
      <template #actions>
        <Button v-if="canManage" variant="solid" label="Add method" @click="showAdd = true" />
      </template>
    </PageHeader>

    <div class="body-container space-y-4 pb-40 pt-5">
      <div v-if="methods.loading && !methods.data" class="space-y-3">
        <LoadingText :lines="4" />
      </div>

      <div
        v-else-if="!ordered.length"
        class="rounded border border-dashed border-outline-gray-2 px-6 py-12 text-center"
      >
        <p class="text-p-base text-ink-gray-6">No payment methods yet.</p>
        <p class="mt-1 text-p-sm text-ink-gray-5">
          Add a card or UPI Autopay so invoices can be charged automatically.
        </p>
      </div>

      <ul v-else class="space-y-2">
        <li
          v-for="(pm, index) in ordered"
          :key="pm.name"
          class="flex items-center gap-3 rounded border border-outline-gray-1 px-4 py-3"
        >
          <span :class="[methodIcon(pm.method_type), 'size-5 text-ink-gray-5']" />
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
          <Dropdown v-if="canManage" :options="rowActions(pm, index)" placement="right">
            <Button variant="ghost" :loading="busy">
              <template #icon><span class="lucide-ellipsis size-4" /></template>
            </Button>
          </Dropdown>
        </li>
      </ul>

      <p v-if="ordered.length > 1" class="text-p-sm text-ink-gray-5">
        Charges try the methods top-down; if one fails, billing falls back to the next.
      </p>
    </div>

    <AddMethodDialog v-model="showAdd" @done="methods.reload()" />
  </div>
</template>
