import { call, frappeRequest, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { API, method, methodV1 } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage } from '@/lib/feedback'
import type { PartnerLink, PartnerPreview, TeamCustomers } from '@/types/api'

/** The active team's partner, for the customer side. */
export function useTeamPartner() {
	const partnerCall = useCall<PartnerLink | null, { team: string }>({
		url: method(API.getTeamPartner),
		params: teamParams,
		refetch: true,
		immediate: false,
	})
	whenTeamReady(() => partnerCall.reload())

	return {
		link: computed(() => partnerCall.data ?? null),
		loading: computed(() => partnerCall.loading),
		error: computed(() =>
			partnerCall.error
				? getErrorMessage(partnerCall.error, "Your partner couldn't be loaded.")
				: '',
		),
		reload: () => partnerCall.reload(),
	}
}

/** The active partner team's code and customers, for the partner side. */
export function useTeamCustomers() {
	const customersCall = useCall<TeamCustomers, { team: string }>({
		url: method(API.getTeamCustomers),
		params: teamParams,
		refetch: true,
		immediate: false,
	})
	whenTeamReady(() => customersCall.reload())

	return {
		customers: computed(() => customersCall.data ?? null),
		loading: computed(() => customersCall.loading),
		error: computed(() =>
			customersCall.error
				? getErrorMessage(
						customersCall.error,
						"Your customers couldn't be loaded.",
					)
				: '',
		),
		reload: () => customersCall.reload(),
	}
}

export function findPartner(
	team: string,
	code: string,
): Promise<PartnerPreview> {
	return frappeRequest<PartnerPreview>({
		url: methodV1(API.getPartnerByCode),
		method: 'GET',
		params: { team, code },
	})
}

export function addPartner(
	team: string,
	code: string,
	reference: string | null,
): Promise<PartnerLink> {
	return call<PartnerLink>(API.addPartner, { team, code, reference })
}

export function endPartnerLink(
	link: string,
	reason: string,
): Promise<PartnerLink> {
	return call<PartnerLink>(API.endPartnerLink, { link, reason })
}

/** The partner a Frappe Connect link asks to add: `/dashboard/partner?code=&reference=`. The
 *  values stay in the URL until they are used, so they survive sign-up and onboarding. */
export function usePartnerLinkIntent() {
	const route = useRoute()
	const router = useRouter()

	const read = (key: string): string => {
		const value = route.name === 'Partner' ? route.query[key] : undefined
		return typeof value === 'string' ? value : ''
	}

	return {
		code: computed(() => read('code')),
		reference: computed(() => read('reference') || null),
		clear: () => router.replace({ query: {} }),
	}
}
