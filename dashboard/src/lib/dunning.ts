import type { NextPayment } from '@/types/billing'

/** How a step reads: a charge we wait on, a retry to come, or a suspension. */
export type DunningTone = 'neutral' | 'warning' | 'danger'

export interface DunningStep {
	label: string
	date: string
	tone: DunningTone
	/** What the date means for the customer. */
	hint: string
}

/** A missed bill's next step on the dunning ladder, or undefined while none is missed. */
export function getDunningStep(
	payment: NextPayment | null | undefined,
): DunningStep | undefined {
	if (payment?.suspended_since) {
		return {
			label: 'Suspended since',
			date: payment.suspended_since,
			tone: 'danger',
			hint: 'Your servers are stopped. Pay the bill to start them again.',
		}
	}
	if (payment?.payment_in_progress_since) {
		return {
			label: 'Payment in progress',
			date: payment.payment_in_progress_since,
			tone: 'neutral',
			hint: 'We are waiting for your bank to confirm this payment.',
		}
	}
	if (payment?.next_retry_on) {
		return {
			label: 'Next retry',
			date: payment.next_retry_on,
			tone: 'warning',
			hint: 'We will try to charge your payment method again on this date.',
		}
	}
	if (payment?.suspends_on) {
		return {
			label: 'Suspends on',
			date: payment.suspends_on,
			tone: 'danger',
			hint: 'Your servers stop on this date if the bill stays unpaid.',
		}
	}

	return undefined
}
