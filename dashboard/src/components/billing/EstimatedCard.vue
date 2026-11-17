<script setup lang="ts">
import {
	Alert,
	Badge,
	Button,
	Dialog,
	dayjs,
	LoadingText,
	TextInput,
	Tooltip,
	useCall,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import TranslatedText from '@/components/common/TranslatedText.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { useSpendingLimits } from '@/composables/useSpendingLimits'
import { whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { currencySymbol, money } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { BillingSettings } from '@/types/billing'

defineProps<{ active?: boolean }>()
defineEmits<{ open: []; openTiers: [] }>()

const { forecast, currency } = useBillingOverview()
const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()
const {
	current: tierCurrent,
	spendingLimit: limit,
	runningMonthly: running,
	limitKnown,
	limitFailed,
} = useSpendingLimits()

const loading = computed(() => forecast.loading && !forecast.data)
const fc = computed(() => forecast.data)
// The headline is what the cycle will cost with tax, the same figure the card is
// charged. The budget alert compares the cycle before tax; the spending limit is
// compared with what runs now, the figure the server-create check uses.
const projected = computed(() => Number(fc.value?.projected_total ?? 0))
const taxAmount = computed(() => Number(fc.value?.tax_amount ?? 0))
const subtotal = computed(() => Number(fc.value?.subtotal ?? 0))
const hasCycle = computed(() => projected.value > 0)
const daysRemaining = computed(() => fc.value?.days_remaining ?? null)

const cycleLabel = computed(() => {
	if (!fc.value?.period_start || !fc.value.period_end) return __('This cycle')

	const start = dayjs(fc.value.period_start)

	const range = [
		start.format('MMMM'),
		start.format('D'),
		dayjs(fc.value.period_end).format('D MMM'),
	]
	return __('{0} cycle · {1} – {2}', range)
})

const scale = computed(() => Math.max(running.value, limit.value))

const percentOf = (amount: number): string =>
	`${scale.value ? (amount / scale.value) * 100 : 0}%`

const withinLimit = computed(() =>
	limit.value ? Math.min(running.value, limit.value) : running.value,
)

const overLimit = computed(() =>
	limit.value ? Math.max(0, running.value - limit.value) : 0,
)

// ── Billing alert (spend-alert threshold) ────────────────────────────────────
// Notify the team once projected spend before tax crosses this amount (0 = off).
// Stored on the Billing Profile via get/save_billing_settings.
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
	() => spendAlert.value > 0 && subtotal.value >= spendAlert.value,
)

const near = computed(
	() =>
		spendAlert.value > 0 &&
		!crossed.value &&
		subtotal.value >= 0.8 * spendAlert.value,
)

const alertLabel = computed(() => {
	if (spendAlert.value <= 0) return __('Set a budget alert')

	const amount = money(spendAlert.value, currency.value)
	if (crossed.value) return __('Over your {0} alert before tax', [amount])
	if (near.value) return __('Nearing your {0} alert before tax', [amount])

	return __('Budget alert at {0} before tax', [amount])
})

const alertTint = computed(() =>
	crossed.value ? 'text-ink-red-7' : near.value ? 'text-ink-amber-6' : '',
)

// Dialog: edit against a draft so Cancel leaves the live value untouched.
const dialogOpen = ref(false)
const draft = ref(0)
const formError = ref('')

function openDialog(): void {
	draft.value = spendAlert.value
	formError.value = ''
	dialogOpen.value = true
}

watch(draft, () => (formError.value = ''))

async function submitAlert(): Promise<void> {
	try {
		await saveAlert.submit({
			team: activeTeam.value!,
			spend_alert_threshold: Number(draft.value) || 0,
		})

		if (saveAlert.error) throw saveAlert.error

		spendAlert.value = Number(draft.value) || 0
		successToast(__('Billing alert saved'))
		dialogOpen.value = false
		settings.reload()
	} catch (e) {
		formError.value = getErrorMessage(
			e,
			__("The budget alert couldn't be saved."),
		)
	}
}

const saveBudgetAlertErrorTitle = __("Couldn't save the budget alert")
</script>

<template>
	<div
		class="flex flex-col gap-4 px-4 py-3 transition-colors"
		:class="active ? 'bg-surface-gray-1' : ''"
	>
		<div class="flex items-center justify-between gap-3">
			<h2 class="flex items-center gap-2 text-sm-medium text-ink-gray-6">
				<span
					class="size-1.5 rounded-9 ring-[3px]"
					:class="
						overLimit
							? 'bg-surface-amber-5 ring-outline-amber-2'
							: 'bg-surface-gray-6 ring-outline-gray-1'
					"
					aria-hidden="true"
				/>
				{{ cycleLabel }}
			</h2>

			<div class="flex items-center gap-2">
				<Tooltip v-if="canManageBilling" :text="alertLabel">
					<Button size="xs" :label="__('Budget alerts')" @click="openDialog">
						<template #icon>
							<span
								class="lucide-bell size-4"
								:class="alertTint || 'text-ink-gray-6'"
								aria-hidden="true"
							/>
						</template>
					</Button>
				</Tooltip>
			</div>
		</div>

		<LoadingText v-if="loading" :lines="3" class="w-56" />

		<template v-else>
			<div class="flex flex-col gap-1">
				<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
					<span
						class="text-4xl-semibold leading-tight tabular-nums text-ink-gray-9"
					>
						{{ money(projected, currency) }}
					</span>
					<span v-if="!hasCycle" class="text-base text-ink-gray-5">
						{{ __('nothing billed yet this cycle') }}
					</span>
					<Badge
						v-if="hasCycle && daysRemaining != null"
						:label="__('Bills in {0} days', [daysRemaining])"
					/>
				</div>

				<p v-if="hasCycle" class="text-sm text-ink-gray-6">
					<span class="tabular-nums">{{ money(subtotal, currency) }}</span>
					<template v-if="taxAmount">
						+
						<span class="tabular-nums">{{ money(taxAmount, currency) }}</span>
						{{ fc?.tax_label || fc?.tax_type || __('tax') }}
					</template>
					·
					<button
						type="button"
						class="text-ink-gray-9 underline decoration-dotted underline-offset-[3px] transition-colors hover:decoration-solid"
						@click="$emit('open')"
					>
						{{ __('See breakdown') }}
					</button>
				</p>
			</div>

			<p v-if="limitFailed" class="text-sm text-ink-gray-6">
				{{ __("Couldn't load your spending limit.") }}
			</p>

			<LoadingText v-else-if="!limitKnown" :lines="2" class="w-56" />

			<div v-else class="flex flex-col gap-2">
				<div
					class="flex flex-wrap justify-between gap-x-3 gap-y-1 text-sm text-ink-gray-6"
				>
					<span>
						<TranslatedText :text="__('Running now: {0} a month before tax')">
							<template #0>
								<span class="tabular-nums text-ink-gray-9"
									>{{ money(running, currency) }}</span
								>
							</template>
						</TranslatedText>
					</span>

					<span v-if="overLimit" class="tabular-nums text-ink-amber-6">
						{{ __('{0} over the limit', [money(overLimit, currency)]) }}
					</span>
				</div>

				<div class="relative h-2 overflow-hidden rounded-2 bg-surface-gray-2">
					<div
						class="absolute inset-y-0 left-0 bg-surface-gray-10 transition-[width] duration-300"
						:style="{ width: percentOf(withinLimit) }"
					/>
					<div
						v-if="overLimit"
						class="absolute inset-y-0 bg-[repeating-linear-gradient(135deg,var(--surface-amber-5)_0_6px,var(--surface-amber-7)_6px_12px)] transition-[width] duration-300"
						:style="{ left: percentOf(limit), width: percentOf(overLimit) }"
					/>
					<div
						v-if="limit"
						class="absolute inset-y-0 -ml-px w-0.5 bg-surface-base"
						:style="{ left: percentOf(limit) }"
						aria-hidden="true"
					/>
				</div>

				<div class="text-sm text-ink-gray-6">
					<span v-if="limit && tierCurrent?.tier">
						<TranslatedText
							:text="__('Spending limit {0} on the {1}. Taxes are added on top.')"
						>
							<template #0>
								<span class="tabular-nums text-ink-gray-9"
									>{{ money(limit, currency) }}</span
								>
							</template>
							<template #1>
								<button
									type="button"
									class="text-ink-gray-9 underline decoration-dotted underline-offset-[3px] transition-colors hover:decoration-solid"
									@click="$emit('openTiers')"
								>
									{{ __('{0} tier', [tierCurrent?.tier]) }}
								</button>
							</template>
						</TranslatedText>
					</span>
					<!-- A manual limit can exist without a tier. -->
					<span v-else-if="limit">
						<TranslatedText
							:text="__('Spending limit {0}. Taxes are added on top.')"
						>
							<template #0>
								<span class="tabular-nums text-ink-gray-9"
									>{{ money(limit, currency) }}</span
								>
							</template>
						</TranslatedText>
					</span>
					<button
						v-else
						type="button"
						class="text-ink-gray-9 underline underline-offset-[3px]"
						@click="$emit('openTiers')"
					>
						{{ __('Spending limits') }}
					</button>
				</div>
			</div>
		</template>

		<Dialog v-model:open="dialogOpen" :title="__('Set a budget alert')">
			<template #default>
				<Alert
					v-if="formError"
					class="mb-4"
					theme="red"
					:title="saveBudgetAlertErrorTitle"
					:description="formError"
				/>
				<TextInput
					v-model="draft"
					autofocus
					type="number"
					:label="__('Alert me above, excluding tax ({0})', [currencySymbol(currency)])"
					min="0"
					placeholder="20000"
				/>
				<p class="mt-2 text-p-sm text-ink-gray-5">
					{{ __("We'll notify the team once projected spend before tax crosses this. Set 0 to turn it off.") }}
				</p>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button :label="__('Cancel')" @click="dialogOpen = false" />
					<Button
						variant="solid"
						:label="__('Set alert')"
						:loading="saveAlert.loading"
						@click="submitAlert"
					/>
				</div>
			</template>
		</Dialog>
	</div>
</template>
