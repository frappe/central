<script setup lang="ts">
import { Button, Dialog, FormControl, LoadingText, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { shortDate } from '@/lib/date'
import { currencySymbol, money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { BillingSettings } from '@/types/billing'

// Estimated this cycle — the projected month-end bill, when it bills + days left,
// and the configurable billing alert (spend-alert threshold). Mirrors the FC v2
// prototype: the alert is a quiet ghost button pinned to the card's foot that
// tints amber/red as spend nears/crosses the threshold, and opens a small dialog.
// Reads get_forecast (+ get_billing_settings).
const { forecast, currency } = useBillingOverview()
const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const loading = computed(() => forecast.loading && !forecast.data)
const fc = computed(() => forecast.data)
const projected = computed(() => Number(fc.value?.projected_total ?? 0))
const billsOn = computed(() =>
	fc.value?.period_end ? shortDate(fc.value.period_end) : '',
)
const daysRemaining = computed(() => fc.value?.days_remaining ?? null)

// ── Billing alert (spend-alert threshold) ────────────────────────────────────
// Notify the team once projected spend crosses this amount (0 = off). Stored on
// the Billing Profile via get/save_billing_settings.
const settings = useCall<BillingSettings, { team: string }>({
	url: method(API.billingSettings),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
const saveAlert = useCall<
	unknown,
	{ team: string; spend_alert_threshold: number }
>({
	url: method(API.saveBillingSettings),
	method: 'POST',
	immediate: false,
})
whenTeamReady(() => settings.reload())

const spendAlert = ref(0)
watch(
	() => settings.data,
	(d) => {
		if (d) spendAlert.value = d.spend_alert_threshold ?? 0
	},
	{ immediate: true },
)

// Alert relationship to the current estimate, so the button says something useful
// at a glance and only tints when it's worth noticing.
const crossed = computed(
	() => spendAlert.value > 0 && projected.value >= spendAlert.value,
)
const near = computed(
	() =>
		spendAlert.value > 0 &&
		!crossed.value &&
		projected.value >= 0.8 * spendAlert.value,
)
const alertLabel = computed(() => {
	if (spendAlert.value <= 0) return 'Set a budget alert'
	if (crossed.value)
		return `Over your ${money(spendAlert.value, currency.value)} alert`
	if (near.value)
		return `Nearing your ${money(spendAlert.value, currency.value)} alert`
	return `Budget alert at ${money(spendAlert.value, currency.value)}`
})
const alertTint = computed(() =>
	crossed.value ? '!text-ink-red-3' : near.value ? '!text-ink-amber-3' : '',
)

// Dialog: edit against a draft so Cancel leaves the live value untouched.
const dialogOpen = ref(false)
const draft = ref(0)
function openDialog(): void {
	draft.value = spendAlert.value
	dialogOpen.value = true
}
async function submitAlert(): Promise<void> {
	try {
		await saveAlert.submit({
			team: activeTeam.value!,
			spend_alert_threshold: Number(draft.value) || 0,
		})
		spendAlert.value = Number(draft.value) || 0
		successToast('Billing alert saved.')
		dialogOpen.value = false
		settings.reload()
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<div
		class="flex flex-col rounded-xl border border-outline-gray-2 bg-surface-elevation-1 p-5"
	>
		<div class="flex h-6 items-center">
			<span class="text-p-sm text-ink-gray-5">Estimated this cycle</span>
		</div>

		<div v-if="loading" class="mt-2 w-32">
			<LoadingText :lines="1" />
		</div>
		<template v-else>
			<p class="mt-1.5 text-2xl font-semibold tabular-nums text-ink-gray-9">
				{{ money(projected, currency) }}
			</p>
			<p class="mt-1.5 text-p-sm text-ink-gray-5">
				<template v-if="billsOn">Bills {{ billsOn }}</template>
				<template v-if="daysRemaining != null">
					· {{ daysRemaining }} days left</template
				>
			</p>

			<div v-if="canManageBilling" class="mt-auto pt-4">
				<Button
					variant="ghost"
					size="sm"
					class="-ml-2"
					:class="alertTint"
					:label="alertLabel"
					@click="openDialog"
				>
					<template #prefix
						><span class="lucide-bell size-4" aria-hidden="true" /></template
					>
				</Button>
			</div>
		</template>

		<Dialog v-model:open="dialogOpen" title="Set a budget alert">
			<template #default>
				<FormControl
					v-model="draft"
					type="number"
					:label="`Alert me above (${currencySymbol(currency)})`"
					min="0"
					placeholder="20000"
				/>
				<p class="mt-2 text-p-sm text-ink-gray-5">
					We'll notify the team once projected spend crosses this. Set 0 to turn
					it off.
				</p>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button label="Cancel" @click="dialogOpen = false" />
					<Button
						variant="solid"
						label="Set alert"
						:loading="saveAlert.loading"
						@click="submitAlert"
					/>
				</div>
			</template>
		</Dialog>
	</div>
</template>
