<script setup lang="ts">
import { Alert, Button, Dialog, useCall } from 'frappe-ui'
// "Action Required" banner — shown when an INR team's bill goes over what its card
// or UPI may pay automatically and the customer must choose how to keep paying
// (ADR 0005 / payments-inr.md). Calm, not alarming: services keep running; this
// is an invitation to decide. Backend feed: get_collection_status.
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { money } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { CollectionStatus, TopUpDue } from '@/types/billing'

const emit = defineEmits<{ 'add-credit': [amount: number] }>()

const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const status = useCall<CollectionStatus, { team: string }>({
	url: method(API.collectionStatus),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => status.reload())

const s = computed(() => status.data)
const show = computed(() => !!s.value?.action_required)
const currency = computed(() => s.value?.currency || 'INR')

// The card or UPI would be asked for more than it may pay automatically: ask for the
// credit that lets the wallet pay the whole bill. Services keep running either way.
const topUp = computed(() => (show.value ? null : s.value?.top_up_due))
const topUpTitle = __('Add credit before your payment date')
// The amounts and the date come formatted from the server, as the reminder email shows them.
const topUpText = computed(() => {
	const due = topUp.value
	if (!due) return ''
	const text = topUpAsk(due)
	// Earlier credit with no GST paid takes its GST from this top-up, so the ask is more than the gap.
	if (!due.includes_earlier_gst) return text
	return `${text} ${__('This includes GST on earlier credit that had none.')}`
})

function topUpAsk(due: TopUpDue) {
	const {
		amount,
		amount_with_gst: withGst,
		tax_label: taxLabel,
		payment_date: date,
		limit: bareLimit,
		limit_tax_note: limitNote,
	} = due.labels
	const limit = bareLimit ? withNote(bareLimit, limitNote) : null
	if (withGst)
		return topUpTextWithGst(amount, withGst, taxLabel ?? '', date, limit)
	if (!limit)
		return __(
			'Add {0} of credit to your wallet by {1}. No card or UPI is saved to pay the rest.',
			[amount, date],
		)
	return __(
		'Add {0} of credit to your wallet by {1}. Your card or UPI pays only amounts up to {2}.',
		[amount, date, limit],
	)
}

function topUpTextWithGst(
	amount: string,
	withGst: string,
	taxLabel: string,
	date: string,
	limit: string | null,
) {
	if (!limit)
		return __(
			'Add {0} of credit to your wallet by {1} ({2} incl. {3}). No card or UPI is saved to pay the rest.',
			[amount, date, withGst, taxLabel],
		)
	return __(
		'Add {0} of credit to your wallet by {1} ({2} incl. {3}). Your card or UPI pays only amounts up to {4}.',
		[amount, date, withGst, taxLabel, limit],
	)
}

const choosing = ref(false)
const chosen = ref<string | null>(null) // 'Manual Checkout' | 'Prepaid'
const formError = ref('')
watch(chosen, () => (formError.value = ''))

const setMode = useCall<unknown, { team: string; mode: string }>({
	url: method(API.setCollectionMode),
	method: 'POST',
	immediate: false,
})

async function choose(): Promise<void> {
	if (!chosen.value) return
	formError.value = ''
	await setMode.submit({ team: activeTeam.value!, mode: chosen.value })
	if (setMode.error) {
		formError.value = getErrorMessage(
			setMode.error,
			'Could not update how you pay',
		)
		return
	}
	successToast(
		chosen.value === 'Prepaid'
			? __('Prepaid on: your wallet pays first, then your card or UPI')
			: "You'll pay each invoice yourself",
	)
	choosing.value = false
	chosen.value = null
	status.reload()
}

// Tripped by an INR bill over the limit: the card or UPI cannot pay it, so only
// wallet credit gets Prepaid past it. `threshold` is the most the card or UPI may
// pay automatically (at most ₹15,000, lower under a smaller mandate).
const OVER_CEILING_REASONS = [
	'invoice_over_threshold',
	'forecast_over_threshold',
]
const isOverCeiling = computed(
	() =>
		currency.value === 'INR' &&
		OVER_CEILING_REASONS.includes(s.value?.reason ?? ''),
)

const prepaidOverLimitBlurb = computed(() => {
	if (s.value?.threshold == null)
		return __('Add credit to your wallet to cover this bill.')
	return __(
		'Add credit to your wallet to cover this bill. Your card or UPI pays only amounts up to {0}.',
		[limitText(s.value.threshold)],
	)
})

const reasonText = computed(() => {
	const limit = s.value?.threshold
	if (s.value?.reason === 'mandate_failed')
		return __(
			'Your automatic payment approval was cancelled or stopped working. Choose how to pay. Your services keep running.',
		)
	if (s.value?.reason === 'invoice_over_threshold')
		return limit == null
			? __(
					'A bill is over the limit for automatic payments. Your services keep running.',
				)
			: __(
					'A bill is over the {0} limit for automatic payments. Your services keep running.',
					[limitText(limit)],
				)
	const projected = withTaxNote(money(s.value?.projected_total, currency.value))
	return limit == null
		? __(
				'This month is heading to {0}, past the limit for automatic payments. Your services keep running.',
				[projected],
			)
		: __(
				'This month is heading to {0}, past the {1} limit for automatic payments. Your services keep running.',
				[projected, limitText(limit)],
			)
})

// The projection includes tax: "₹11,800.00 (incl. IGST 18%)".
function withTaxNote(amount: string): string {
	return withNote(amount, s.value?.tax_note)
}

// The limit caps amounts that include tax, as the Action Required notice says.
function limitText(limit: number): string {
	return withNote(money(limit, currency.value), s.value?.limit_tax_note)
}

function withNote(amount: string, note?: string | null): string {
	// A format, not text: the note is already translated.
	return note ? `${amount} (${note})` : amount
}

const options = computed(() => [
	{
		key: 'Manual Checkout',
		icon: 'lucide-receipt',
		title: 'Pay each invoice',
		blurb: 'We email you each bill; you pay in a few taps (any amount).',
		fit: 'Best if your usage varies a lot month to month.',
	},
	{
		key: 'Prepaid',
		icon: 'lucide-wallet',
		title: 'Prepaid wallet',
		blurb: isOverCeiling.value
			? prepaidOverLimitBlurb.value
			: __(
					'Your wallet pays first. When it is short, we charge your card or UPI.',
				),
		fit: 'Best for hands-off, predictable spending.',
	},
])
</script>

<template>
	<Alert
		v-if="show && s"
		theme="amber"
		title="Action required: choose how to keep paying"
		:primary-action="canManageBilling ? { label: 'Choose how to pay', onClick: () => { choosing = true } } : undefined"
	>
		<template #description>{{ reasonText }}</template>
	</Alert>

	<Alert
		v-else-if="topUp"
		theme="blue"
		:title="topUpTitle"
		:primary-action="canManageBilling ? { label: __('Add credit'), onClick: () => emit('add-credit', topUp!.amount) } : undefined"
	>
		<template #description>{{ topUpText }}</template>
	</Alert>

	<Dialog v-model:open="choosing" title="How do you want to pay?">
		<template #default>
			<Alert
				v-if="formError"
				class="mb-4"
				theme="red"
				title="Couldn't change how you pay"
				:description="formError"
			/>
			<div class="grid gap-3 sm:grid-cols-2">
				<button
					v-for="o in options"
					:key="o.key"
					type="button"
					class="flex flex-col gap-2 rounded-6 border p-4 text-left transition-colors"
					:class="
            chosen === o.key
              ? 'border-outline-gray-4 bg-surface-gray-2'
              : 'border-outline-gray-2 hover:border-outline-gray-3'
          "
					@click="chosen = o.key"
				>
					<span
						:class="o.icon"
						class="size-5 text-ink-gray-7"
						aria-hidden="true"
					/>
					<span class="text-base-medium text-ink-gray-9">{{ o.title }}</span>
					<span class="text-p-sm text-ink-gray-6">{{ o.blurb }}</span>
					<span class="mt-auto text-p-sm text-ink-gray-5">{{ o.fit }}</span>
				</button>
			</div>
			<p v-if="s?.mandate_gap_note" class="mt-3 text-p-sm text-ink-gray-6">
				{{ s.mandate_gap_note }}
			</p>
			<p class="mt-3 text-p-sm text-ink-gray-5">
				You can switch anytime in Billing settings.
			</p>
		</template>
		<template #actions>
			<Button
				variant="solid"
				label="Confirm"
				class="w-full"
				:loading="setMode.loading"
				:disabled="!chosen"
				@click="choose"
			/>
		</template>
	</Dialog>
</template>
