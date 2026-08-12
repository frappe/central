<script setup lang="ts">
import { Button, Dialog, FormControl, LoadingText, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { ordinalDate } from '@/lib/date'
import { currencySymbol, money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { BillingSettings } from '@/types/billing'

// Estimated this cycle — the projected month-end bill, when it bills + days left,
// and the configurable billing alert (spend-alert threshold). Mirrors the FC v2
// prototype: the alert is a quiet ghost button pinned to the card's foot that
// tints amber/red as spend nears/crosses the threshold, and opens a small dialog.
// Reads get_forecast (+ get_billing_settings).
//
// The projection is never quoted as a bare number: the engine already knows which
// part of it is a locked rate over elapsed days and which is inferred from usage
// nobody has finished (projection/basis.py), and the customer is owed that split.
// The bar and its legend are that split; the breakdown tray is the detail.
defineProps<{ active?: boolean }>()
defineEmits<{ open: [] }>()
const { forecast, currency } = useBillingOverview()
const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const loading = computed(() => forecast.loading && !forecast.data)
const fc = computed(() => forecast.data)
const projected = computed(() => Number(fc.value?.projected_total ?? 0))
const billsOn = computed(() =>
	fc.value?.period_end ? ordinalDate(fc.value.period_end) : '',
)
const daysRemaining = computed(() => fc.value?.days_remaining ?? null)

// Owed vs inferred. Fall back to treating the whole projection as owed when the
// split is absent (an older cached response), never the other way round — calling
// a fact an estimate is the less honest failure.
const measured = computed(() => Number(fc.value?.measured ?? projected.value))
const estimated = computed(() => Number(fc.value?.estimated ?? 0))
const hasEstimates = computed(() => Boolean(fc.value?.has_estimates))
const taxAmount = computed(() => Number(fc.value?.tax_amount ?? 0))
// Nothing accrued yet: the tray would open on an empty list, so the affordance
// that opens it is not offered. An action that leads nowhere is worse than no
// action — it reads as something being broken.
const hasCycle = computed(() => projected.value > 0)
const taxLabel = computed(() => fc.value?.tax_type || 'tax')
const measuredPct = computed(() => {
	const total = measured.value + estimated.value
	return total > 0 ? Math.round((measured.value / total) * 100) : 100
})

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
		successToast('Billing alert saved')
		dialogOpen.value = false
		settings.reload()
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<div
		class="rounded-lg border bg-surface-base p-5 transition-colors"
		:class="active ? 'border-outline-gray-4' : 'border-outline-gray-2'"
	>
		<div class="flex h-6 items-center justify-between gap-2">
			<button
				v-if="hasCycle"
				type="button"
				class="text-p-sm text-ink-gray-5 transition-colors hover:text-ink-gray-7"
				@click="$emit('open')"
			>
				This cycle
			</button>
			<span v-else class="text-p-sm text-ink-gray-5">This cycle</span>
			<Button
				v-if="hasCycle"
				variant="ghost"
				size="sm"
				label="Breakdown"
				@click="$emit('open')"
			>
				<template #suffix>
					<span class="lucide-chevron-right size-4" aria-hidden="true" />
				</template>
			</Button>
		</div>

		<div v-if="loading" class="mt-2 w-40">
			<LoadingText :lines="2" />
		</div>
		<template v-else>
			<!-- The headline figure of the page. -->
			<p class="mt-1.5 text-3xl-semibold tabular-nums text-ink-gray-9">
				{{ money(projected, currency) }}
			</p>
			<p class="mt-1 text-p-sm text-ink-gray-5">
				<template v-if="!hasCycle">
					Nothing has been billed yet this cycle
				</template>
				<template v-else>
					<template v-if="billsOn">Bills {{ billsOn }}</template>
					<template v-if="daysRemaining != null">
						· {{ daysRemaining }} days left</template
					>
				</template>
			</p>

			<!-- Split bar: solid is owed, hatched is inferred. Only drawn when part
			     of the figure actually is an estimate — a bill that is entirely fact
			     should not be given a bar that implies doubt. -->
			<template v-if="hasEstimates">
				<div
					class="mt-4 flex h-2 overflow-hidden rounded-full bg-surface-gray-2"
					aria-hidden="true"
				>
					<span
						class="bg-surface-blue-5"
						:style="{ width: `${measuredPct}%` }"
					/>
					<span class="estimated-fill flex-1" />
				</div>
				<div class="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1">
					<span class="flex items-center gap-1.5 text-p-sm text-ink-gray-6">
						<span
							class="size-2 shrink-0 rounded-sm bg-surface-blue-5"
							aria-hidden="true"
						/>
						{{ money(measured, currency) }} already owed
					</span>
					<span class="flex items-center gap-1.5 text-p-sm text-ink-gray-6">
						<span
							class="estimated-fill size-2 shrink-0 rounded-sm"
							aria-hidden="true"
						/>
						{{ money(estimated, currency) }} estimated
					</span>
				</div>
			</template>

			<div
				class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-outline-gray-1 pt-3"
			>
				<Button
					v-if="canManageBilling"
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
				<span v-else />
				<span v-if="taxAmount" class="text-p-sm text-ink-gray-5">
					incl. {{ money(taxAmount, currency) }} {{ taxLabel }}
				</span>
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

<style scoped>
/* Estimated spend is drawn as a hatch rather than a second colour: it is the same
   money, differing only in whether it has happened yet. */
.estimated-fill {
	background-image: repeating-linear-gradient(
		45deg,
		var(--surface-blue-4) 0 3px,
		var(--surface-blue-2) 3px 6px
	);
}
</style>
