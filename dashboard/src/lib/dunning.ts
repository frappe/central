import type { NextPayment } from '@/types/billing'

export interface DunningStep {
	label: string
	date: string
	/** True once the step stops the team's servers, or already has. */
	isSuspension: boolean
}

/** A missed bill's next step on the dunning ladder, or undefined while none is missed. */
export function getDunningStep(
	payment: NextPayment | null | undefined,
): DunningStep | undefined {
	if (payment?.suspended_since) {
		return {
			label: 'Suspended since',
			date: payment.suspended_since,
			isSuspension: true,
		}
	}
	if (payment?.next_retry_on) {
		return {
			label: 'Next retry',
			date: payment.next_retry_on,
			isSuspension: false,
		}
	}
	if (payment?.suspends_on) {
		return {
			label: 'Suspends on',
			date: payment.suspends_on,
			isSuspension: true,
		}
	}

	return undefined
}
