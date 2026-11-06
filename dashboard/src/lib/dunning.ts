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

/**
 * A missed bill's steps on the dunning ladder, next step first, or none while no bill is
 * missed. An overdue bill with a payment in progress has two: the payment and the suspension.
 */
export function getDunningSteps(
	payment: NextPayment | null | undefined,
): DunningStep[] {
	if (payment?.suspended_since) {
		return [
			{
				label: 'Suspended since',
				date: payment.suspended_since,
				tone: 'danger',
				hint: 'Your servers are stopped. Pay the bill to start them again.',
			},
		]
	}

	const steps: DunningStep[] = []
	if (payment?.payment_in_progress_since) {
		steps.push({
			label: 'Payment in progress',
			date: payment.payment_in_progress_since,
			tone: 'neutral',
			hint: 'We are waiting for your bank to confirm this payment.',
		})
	}
	if (payment?.next_retry_on) {
		steps.push({
			label: 'Next retry',
			date: payment.next_retry_on,
			tone: 'warning',
			hint: 'We will try to charge your payment method again on this date.',
		})
	}
	if (payment?.suspends_on) {
		steps.push({
			label: 'Suspends on',
			date: payment.suspends_on,
			tone: 'danger',
			hint: payment.payment_in_progress_since
				? 'Your servers stop on this date if the payment fails. Add credit to your wallet to avoid this. If the payment also goes through, we will refund it.'
				: 'Your servers stop on this date if the bill stays unpaid.',
		})
	}

	return steps
}
