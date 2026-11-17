<script setup lang="ts">
import { Alert, useCall } from 'frappe-ui'
// "Action Required" banner — shown when an INR team's bill goes over what its card
// or UPI may pay automatically and the customer must choose how to keep paying
// (ADR 0005 / payments-inr.md). Calm, not alarming: services keep running; this
// is an invitation to decide. Backend feed: get_collection_status.
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import CollectionModeDialog from '@/components/billing/CollectionModeDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { limitText, withNote } from '@/lib/collectionText'
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

const reasonText = computed(() => {
	const st = s.value
	if (!st) return ''
	const limit = st.threshold
	// The limit caps amounts that include tax, as the Action Required notice says.
	const limitLabel = limit == null ? '' : limitText(st, limit)
	if (st.reason === 'mandate_failed')
		return __(
			'Your automatic payment approval was cancelled or stopped working. Choose how to pay. Your services keep running.',
		)
	if (st.reason === 'invoice_over_threshold')
		return limit == null
			? __(
					'A bill is over the limit for automatic payments. Your services keep running.',
				)
			: __(
					'A bill is over the {0} limit for automatic payments. Your services keep running.',
					[limitLabel],
				)
	const projected = withTaxNote(money(st.projected_total, currency.value))
	return limit == null
		? __(
				'This month is heading to {0}, past the limit for automatic payments. Your services keep running.',
				[projected],
			)
		: __(
				'This month is heading to {0}, past the {1} limit for automatic payments. Your services keep running.',
				[projected, limitLabel],
			)
})

function withTaxNote(amount: string): string {
	return withNote(amount, s.value?.tax_note)
}
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

	<CollectionModeDialog
		v-if="s"
		v-model:open="choosing"
		:status="s"
		@changed="status.reload()"
	/>
</template>
