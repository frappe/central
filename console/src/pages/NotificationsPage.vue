<script setup lang="ts">
import { reactive, watch, ref } from 'vue'
import { useCall, Badge, Button, Switch, FormControl, LoadingText } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { useCapabilities } from '@/composables/useCapabilities'
import { notificationTheme } from '@/lib/status'
import { successToast, errorToast } from '@/lib/toast'
import type { NotificationLog, NotificationPreferences, BillingSettings } from '@/types/billing'

// Top-level Notifications surface (#72, the bell) — the billing notification feed
// (what we sent / suppressed) + per-event-type delivery toggles + the spend-alert
// threshold. The feed is read-only; preferences + alert need billing:manage.
const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const params = () => ({ team: activeTeam.value! })
const feed = useCall<NotificationLog[], { team: string }>({
  url: method(API.notifications), params, immediate: false, refetch: true,
})
const prefs = useCall<NotificationPreferences, { team: string }>({
  url: method(API.notificationPreferences), params, immediate: false, refetch: true,
})
const settings = useCall<BillingSettings, { team: string }>({
  url: method(API.billingSettings), params, immediate: false, refetch: true,
})
whenTeamReady(() => {
  feed.reload()
  prefs.reload()
  settings.reload()
})

// Each toggle, in display order, paired with its preference key.
const PREF_FIELDS = [
  { key: 'notify_payment_success', label: 'Payment success' },
  { key: 'notify_payment_failure', label: 'Payment failure' },
  { key: 'notify_payment_retry', label: 'Payment retry' },
  { key: 'notify_invoice_overdue', label: 'Invoice overdue' },
  { key: 'notify_credit_low', label: 'Low credit balance' },
  { key: 'notify_card_expiry', label: 'Card expiry' },
  { key: 'notify_mandate_reauth', label: 'Mandate re-authorisation' },
  { key: 'notify_trial_expiring', label: 'Trial expiring' },
]

const form = reactive<Record<string, boolean>>({})
watch(
  () => prefs.data,
  (d) => {
    if (!d) return
    for (const f of PREF_FIELDS) form[f.key] = !!d[f.key]
  },
  { immediate: true },
)

const save = useCall<unknown, Record<string, unknown>>({
  url: method(API.saveNotificationPreferences), immediate: false,
})
async function submit(): Promise<void> {
  try {
    const payload: Record<string, unknown> = { team: activeTeam.value }
    for (const f of PREF_FIELDS) payload[f.key] = form[f.key] ? 1 : 0
    await save.submit(payload)
    successToast('Notification preferences saved.')
    prefs.reload()
  } catch (e) {
    errorToast(e)
  }
}

// Spend alert threshold — notify once projected spend crosses this amount (0 =
// off). Stored on the Billing Profile; saved on its own.
const spendAlert = ref(0)
watch(
  () => settings.data,
  (d) => {
    if (d) spendAlert.value = d.spend_alert_threshold ?? 0
  },
  { immediate: true },
)

const saveAlert = useCall<unknown, { team: string; spend_alert_threshold: number }>({
  url: method(API.saveBillingSettings), immediate: false,
})
async function submitAlert(): Promise<void> {
  try {
    await saveAlert.submit({ team: activeTeam.value!, spend_alert_threshold: spendAlert.value })
    successToast('Spend alert saved.')
    settings.reload()
  } catch (e) {
    errorToast(e)
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Notifications" />

    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="mx-auto w-full max-w-2xl space-y-8 px-5 py-6">
        <!-- Spend alert -->
        <section class="space-y-3">
          <div>
            <h2 class="text-base text-ink-gray-9">Spend alert</h2>
            <p class="text-p-sm text-ink-gray-5">
              Notify the team once projected spend crosses this amount. Set 0 to turn it off.
            </p>
          </div>
          <div class="flex items-end gap-3">
            <FormControl
              v-model="spendAlert"
              type="number"
              label="Threshold"
              class="w-48"
              :disabled="!canManageBilling"
            />
            <Button
              v-if="canManageBilling"
              variant="solid"
              label="Save alert"
              :loading="saveAlert.loading"
              @click="submitAlert"
            />
          </div>
        </section>

        <!-- Preferences -->
        <section class="space-y-3 border-t border-outline-gray-1 pt-8">
          <div>
            <h2 class="text-base text-ink-gray-9">Notification preferences</h2>
            <p class="text-p-sm text-ink-gray-5">Choose which billing events notify your team.</p>
          </div>
          <div v-if="prefs.loading && !prefs.data" class="space-y-2">
            <LoadingText :lines="4" />
          </div>
          <div v-else class="divide-y divide-outline-gray-1 rounded border border-outline-gray-1">
            <div
              v-for="f in PREF_FIELDS"
              :key="f.key"
              class="flex items-center justify-between px-4 py-2.5"
            >
              <span class="text-sm text-ink-gray-8">{{ f.label }}</span>
              <Switch v-model="form[f.key]" :disabled="!canManageBilling" />
            </div>
          </div>
          <Button
            v-if="canManageBilling"
            variant="solid"
            label="Save preferences"
            :loading="save.loading"
            @click="submit"
          />
        </section>

        <!-- Feed -->
        <section class="space-y-3 border-t border-outline-gray-1 pt-8">
          <h2 class="text-base text-ink-gray-9">Recent notifications</h2>
          <div v-if="feed.loading && !feed.data" class="space-y-2">
            <LoadingText :lines="5" />
          </div>
          <div
            v-else-if="!feed.data?.length"
            class="rounded border border-dashed border-outline-gray-2 px-6 py-10 text-center text-p-sm text-ink-gray-5"
          >
            No notifications yet.
          </div>
          <ul v-else class="divide-y divide-outline-gray-1 rounded border border-outline-gray-1">
            <li v-for="n in feed.data" :key="n.name" class="px-4 py-3">
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <p class="truncate text-sm text-ink-gray-8">{{ n.subject || n.event_type }}</p>
                  <Badge :theme="notificationTheme(n.status)" :label="n.status" />
                </div>
                <p v-if="n.message" class="mt-0.5 text-p-sm text-ink-gray-6">{{ n.message }}</p>
                <p class="mt-0.5 text-p-sm text-ink-gray-5">
                  {{ n.event_type }}<span v-if="n.channel"> · {{ n.channel }}</span>
                  <span v-if="n.sent_at"> · {{ n.sent_at }}</span>
                </p>
              </div>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>
