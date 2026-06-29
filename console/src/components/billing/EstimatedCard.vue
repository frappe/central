<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useCall, Button, FormControl, LoadingText } from 'frappe-ui'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { useCapabilities } from '@/composables/useCapabilities'
import { API, method } from '@/api/methods'
import { money } from '@/lib/format'
import { shortDate } from '@/lib/date'
import { successToast, errorToast } from '@/lib/toast'
import type { BillingSettings } from '@/types/billing'

// Estimated this cycle — compact summary: the projected month-end bill, when it
// bills + days left, and the configurable billing alert (spend-alert threshold).
// Reads get_forecast (+ get_team_overview for currency, get_billing_settings).
const { forecast, currency } = useBillingOverview()
const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const loading = computed(() => forecast.loading && !forecast.data)
const fc = computed(() => forecast.data)
const projected = computed(() => Number(fc.value?.projected_total ?? 0))
const billsOn = computed(() => (fc.value?.period_end ? shortDate(fc.value.period_end) : ''))
const daysRemaining = computed(() => fc.value?.days_remaining ?? null)

// ── Billing alert (spend-alert threshold) ────────────────────────────────────
// Notify the team once projected spend crosses this amount (0 = off). Stored on
// the Billing Profile via get/save_billing_settings; lives here under the cycle
// estimate so the alert sits next to the number it watches.
const settings = useCall<BillingSettings, { team: string }>({
  url: method(API.billingSettings),
  params: () => ({ team: activeTeam.value! }),
  immediate: false,
  refetch: true,
})
const saveAlert = useCall<unknown, { team: string; spend_alert_threshold: number }>({
  url: method(API.saveBillingSettings),
  immediate: false,
})
whenTeamReady(() => settings.reload())

const spendAlert = ref(0)
const editingAlert = ref(false)
watch(
  () => settings.data,
  (d) => {
    if (d) spendAlert.value = d.spend_alert_threshold ?? 0
  },
  { immediate: true },
)

async function submitAlert(): Promise<void> {
  try {
    await saveAlert.submit({ team: activeTeam.value!, spend_alert_threshold: spendAlert.value })
    successToast('Billing alert saved.')
    editingAlert.value = false
    settings.reload()
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <div class="flex flex-col rounded-lg border border-outline-gray-2 bg-surface-white p-5">
    <div class="flex items-start justify-between gap-2">
      <span class="text-p-sm text-ink-gray-5">Estimated this cycle</span>
      <button
        v-if="canManageBilling && !editingAlert"
        class="grid size-6 place-items-center rounded text-ink-gray-5 hover:bg-surface-gray-3"
        :aria-label="spendAlert > 0 ? 'Edit billing alert' : 'Set billing alert'"
        title="Billing alert"
        @click="editingAlert = true"
      >
        <span class="lucide-bell size-4" aria-hidden="true" />
      </button>
    </div>

    <div v-if="loading" class="mt-2 w-32">
      <LoadingText :lines="1" />
    </div>
    <template v-else>
      <p class="mt-1 text-2xl font-semibold tabular-nums text-ink-gray-9">
        {{ money(projected, currency) }}
      </p>
      <p class="mt-1 text-p-sm text-ink-gray-5">
        <template v-if="billsOn">Bills {{ billsOn }}</template>
        <template v-if="daysRemaining != null"> · {{ daysRemaining }} days left</template>
      </p>
      <p v-if="spendAlert > 0 && !editingAlert" class="mt-1 text-p-sm text-ink-gray-4">
        Alert above {{ money(spendAlert, currency) }}
      </p>
    </template>

    <!-- Inline billing-alert editor -->
    <div v-if="editingAlert" class="mt-3 border-t border-outline-gray-1 pt-3">
      <FormControl
        v-model="spendAlert"
        type="number"
        label="Alert threshold"
        :description="`Notify when projected spend crosses this. Set 0 to turn it off (${currency}).`"
        min="0"
      />
      <div class="mt-2 flex gap-2">
        <Button variant="solid" label="Save" :loading="saveAlert.loading" @click="submitAlert" />
        <Button label="Cancel" @click="editingAlert = false" />
      </div>
    </div>
  </div>
</template>
