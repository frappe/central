import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { submitOrThrow } from '@/lib/frappeCall'
import type { OpenPartnerRequest, PartnerRequestStatus } from '@/types/api'

export interface PartnerRequestAcceptance {
	team: string
	paidByPartner: boolean
	/** Ignored when the partner pays: a partner who pays always gets access. */
	partnerAccess: boolean
}

// Loaded once when the console starts. The onboarding dialog asks the customer to accept.
const requestsCall = useCall<OpenPartnerRequest[]>({
	url: method(API.myPartnerRequests),
})
const acceptCall = useCall<
	{ name: string; status: PartnerRequestStatus; team: string },
	Record<string, string | number>
>({
	url: method(API.acceptPartnerRequest),
	method: 'POST',
	immediate: false,
})

/** The partners Connect asks the signed-in user to accept, newest first. */
export function usePartnerRequests() {
	async function accept(
		request: string,
		{ team, paidByPartner, partnerAccess }: PartnerRequestAcceptance,
	): Promise<void> {
		await submitOrThrow(acceptCall, {
			request,
			team,
			paid_by_partner: paidByPartner ? 1 : 0,
			partner_access: partnerAccess ? 1 : 0,
		})
	}

	return {
		requests: computed(() => requestsCall.data ?? []),
		// An unanswered call counts as no requests, so a failure never blocks onboarding.
		isLoaded: computed(() => requestsCall.isFinished),
		accept,
		reload: () => requestsCall.reload(),
	}
}
