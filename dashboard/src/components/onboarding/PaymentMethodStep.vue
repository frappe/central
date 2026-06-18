<script setup>
import { ref, watch } from 'vue'
import { useCall } from 'frappe-ui'
import { Button, LoadingText } from 'frappe-ui'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'

// Step 2 (optional) — a saved card/UPI Autopay so invoices are charged
// automatically. It needs the saved currency + gateway customer from step 1, so
// the wizard keeps it locked until the billing profile is complete. Completion
// here simply means "at least one method on file".
defineProps({ active: Boolean, complete: Boolean })
const emit = defineEmits(['update:complete', 'advance'])

const { currentTeam } = useTeam()
const methods = useCall({
  url: m(API.paymentMethods),
  params: () => ({ team: currentTeam.value }),
  refetch: true,
})
watch(() => methods.data, (d) => emit('update:complete', !!d?.length), { immediate: true })

const showAdd = ref(false)
function onAdded() {
  methods.reload()
  emit('advance')
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="methods.loading && !methods.data" class="space-y-3">
      <LoadingText :lines="3" />
    </div>

    <ul v-else-if="methods.data?.length" class="space-y-2">
      <li
        v-for="pm in methods.data"
        :key="pm.name"
        class="flex items-center gap-3 rounded border border-outline-gray-1 px-4 py-3"
      >
        <span
          :class="[
            pm.method_type === 'Card' ? 'lucide-credit-card' : 'lucide-smartphone',
            'size-5 text-ink-gray-5',
          ]"
        />
        <p class="truncate text-sm text-ink-gray-8">
          {{ pm.display_label || pm.method_type }}
        </p>
      </li>
    </ul>

    <div
      v-else
      class="rounded border border-dashed border-outline-gray-2 px-6 py-8 text-center"
    >
      <p class="text-p-base text-ink-gray-6">No payment method yet.</p>
      <p class="mt-1 text-p-sm text-ink-gray-5">
        Add a card or UPI Autopay so invoices can be charged automatically — or skip this and
        add one later from Settings.
      </p>
    </div>

    <Button v-if="!methods.data?.length" variant="solid" @click="showAdd = true">
      <template #prefix><span class="lucide-plus size-4" aria-hidden="true" /></template>
      Add payment method
    </Button>

    <AddMethodDialog v-model="showAdd" @done="onAdded" />
  </div>
</template>
