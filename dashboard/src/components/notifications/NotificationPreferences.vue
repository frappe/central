<script setup lang="ts">
import { reactive, watch, computed } from 'vue'
import { Switch, Button } from 'frappe-ui'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams } from '@/composables/useTeamScope'
import { useCapabilities } from '@/composables/useCapabilities'
import { successToast, errorToast } from '@/lib/toast'
import type { NotificationPreferences } from '@/types/billing'

// Email-delivery preferences per billing event — the console home for what was an
// ugly raw Desk form. These gate EMAIL only; the in-app feed always records every
// event, so a failure is never hidden from the dashboard.
const PREFS: { key: string; label: string; hint: string }[] = [
	{
		key: 'notify_payment_failure',
		label: 'Payment failed',
		hint: 'A charge was declined.',
	},
	{
		key: 'notify_payment_retry',
		label: 'Payment retry failed',
		hint: 'A retry of a failed charge was declined.',
	},
	{
		key: 'notify_invoice_overdue',
		label: 'Invoice overdue',
		hint: 'An invoice passed its due date.',
	},
	{
		key: 'notify_credit_low',
		label: 'Credit balance low',
		hint: 'Projected usage is nearing your wallet balance.',
	},
	{
		key: 'notify_card_expiry',
		label: 'Card expired',
		hint: 'A saved card is no longer valid.',
	},
	{
		key: 'notify_mandate_reauth',
		label: 'Mandate re-authorisation',
		hint: 'A UPI Autopay mandate needs re-approval.',
	},
	{
		key: 'notify_trial_expiring',
		label: 'Trial ending',
		hint: 'A trial is about to end.',
	},
	{
		key: 'notify_payment_success',
		label: 'Payment received',
		hint: 'A charge succeeded (receipts).',
	},
]

const { canManageBilling } = useCapabilities()
const state = reactive<Record<string, boolean>>({})

const load = useCall<NotificationPreferences, { team: string }>({
	url: method(API.notificationPreferences),
	params: teamParams,
	immediate: true,
	refetch: true,
})

watch(
	() => load.data,
	(data) => {
		if (!data) return
		for (const { key } of PREFS) state[key] = Boolean(Number(data[key] ?? 1))
	},
	{ immediate: true },
)

const save = useCall<{ saved: boolean }, Record<string, number | string>>({
	url: method(API.saveNotificationPreferences),
	method: 'POST',
	immediate: false,
})

const dirty = computed(() => {
	if (!load.data) return false
	return PREFS.some(
		({ key }) => Boolean(Number(load.data![key] ?? 1)) !== state[key],
	)
})

async function onSave(): Promise<void> {
	try {
		const payload: Record<string, number> = {}
		for (const { key } of PREFS) payload[key] = state[key] ? 1 : 0
		await save.submit(payload)
		await load.reload()
		successToast('Notification preferences saved.')
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<div class="mx-auto max-w-2xl">
		<p class="mb-4 text-p-sm text-ink-gray-5">
			Choose which billing events email you. Your in-app notifications always
			show every event regardless of these settings.
		</p>

		<div
			class="divide-y divide-outline-gray-1 rounded-lg ring-1 ring-outline-gray-1"
		>
			<div
				v-for="pref in PREFS"
				:key="pref.key"
				class="flex items-start justify-between gap-4 px-4 py-3"
			>
				<div class="min-w-0">
					<p class="text-sm text-ink-gray-8">{{ pref.label }}</p>
					<p class="text-p-sm text-ink-gray-5">{{ pref.hint }}</p>
				</div>
				<Switch v-model="state[pref.key]" :disabled="!canManageBilling" />
			</div>
		</div>

		<div v-if="canManageBilling" class="mt-4 flex justify-end">
			<Button
				variant="solid"
				:loading="save.loading"
				:disabled="!dirty"
				@click="onSave"
			>
				Save preferences
			</Button>
		</div>
	</div>
</template>
