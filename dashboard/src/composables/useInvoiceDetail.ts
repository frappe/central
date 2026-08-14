import { useCall } from 'frappe-ui'
import { computed, type MaybeRefOrGetter, toValue, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useCapabilities } from '@/composables/useCapabilities'
import { usePayInvoice } from '@/composables/usePayInvoice'
import { usePayInvoiceCheckout } from '@/composables/usePayInvoiceCheckout'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import type { CollectionStatus, InvoiceDetail } from '@/types/billing'

// One invoice receipt has two hosts: the docked panel on the Invoices page and,
// on a phone where there's no room to dock anything, the /billing/invoices/:name
// page. They frame it differently but read the same invoice under the same
// rules, so the fetch, the payability tests and the pay wiring live here instead
// of in either of them. The caller names the invoice — the selected row on
// desktop, the route param on mobile — and `onPaid` refreshes whatever else that
// host has on screen (the list) once money moves.

// Each presentation owns its own URL space, like settings does: /billing/invoices
// is the list (which opens a receipt beside it on desktop) and the child path is
// the mobile receipt page.
export const INVOICES_PATH = '/billing/invoices'
export const invoicePath = (name: string): string =>
	`${INVOICES_PATH}/${encodeURIComponent(name)}`

export function useInvoiceDetail(
	name: MaybeRefOrGetter<string | null>,
	{ onPaid }: { onPaid?: () => void } = {},
) {
	const { canManageBilling } = useCapabilities()

	const collection = useCall<CollectionStatus, { team: string }>({
		url: method(API.collectionStatus),
		params: teamParams,
		immediate: false,
		refetch: true,
	})
	whenTeamReady(() => collection.reload())

	const detail = useCall<InvoiceDetail, { name: string }>({
		url: method(API.invoice),
		immediate: false,
	})

	// Follow whatever the host points at. A cleared name is not a fetch: the panel
	// keeps rendering the last receipt while it slides out, and blanking the body
	// mid-animation is the thing its `shown` ref exists to prevent.
	watch(
		() => toValue(name),
		(invoice) => {
			if (invoice) detail.submit({ name: invoice })
		},
		{ immediate: true },
	)

	// Open OR Overdue is still collectable — an overdue invoice is the one the customer
	// most needs to settle (dunning failed on the card), so it must offer Pay too.
	const isPayable = computed(() =>
		['open', 'overdue'].includes(String(detail.data?.status).toLowerCase()),
	)
	// The receipt's one pre-items line, and only in the problem state — its single
	// use of color above the fold.
	const isOverdue = computed(
		() =>
			String(detail.data?.status).toLowerCase() === 'overdue' &&
			!!detail.data?.due_date,
	)
	// A charge already in flight (or captured, awaiting the settlement webhook) means
	// the money is moving — show a "settling" status, never a second Pay button.
	const settling = computed(
		() => isPayable.value && !!detail.data?.payment_in_progress,
	)
	// Only offer Pay when something is actually collectable — a zero-due invoice
	// (e.g. a trial Cost Report) must never render a "Pay 0.00" button.
	const hasDue = computed(() => Number(detail.data?.expected_collection) > 0)
	const canPay = computed(
		() =>
			canManageBilling.value &&
			isPayable.value &&
			!settling.value &&
			hasDue.value,
	)

	// Re-read this invoice after a charge, and let the host re-read whatever it
	// shows alongside (the list's status column moves with the receipt).
	function refresh(): void {
		const invoice = toValue(name)
		if (invoice) detail.submit({ name: invoice })
		onPaid?.()
	}
	const { run: payInvoice, loading: paying } = usePayInvoice({
		onDone: refresh,
	})
	const { run: payCheckout, loading: payingCheckout } = usePayInvoiceCheckout({
		onDone: refresh,
	})

	// manual_checkout teams settle on-session (any amount, no ₹15k limit); everyone
	// else uses the off-session charge against their saved method.
	const manualMode = computed(
		() => collection.data?.collection_mode === 'Manual Checkout',
	)
	const payBusy = computed(() => paying.value || payingCheckout.value)
	async function pay(): Promise<void> {
		const invoice = detail.data?.name
		if (!invoice) return
		await (manualMode.value ? payCheckout(invoice) : payInvoice(invoice))
	}

	return { detail, isOverdue, settling, canPay, payBusy, pay }
}
