import { call, frappeRequest, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { API, method, methodV1 } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage } from '@/lib/feedback'
import type {
	PartnerLink,
	PartnerPayer,
	PartnerPreview,
	PartnerRole,
	TeamCustomers,
} from '@/types/api'

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

export function setPartnerRole(
	link: string,
	role: PartnerRole,
): Promise<PartnerLink> {
	return call<PartnerLink>(API.setPartnerRole, { link, role })
}

export function setPartnerPayer(
	link: string,
	payer: PartnerPayer,
): Promise<PartnerLink> {
	return call<PartnerLink>(API.setPartnerPayer, { link, payer })
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

function isoDate(date: Date): string {
	const month = String(date.getMonth() + 1).padStart(2, '0')
	const day = String(date.getDate()).padStart(2, '0')
	return `${date.getFullYear()}-${month}-${day}`
}

/** The 1st of next month: when a change of who pays takes effect. */
export function nextPayerChangeDay(): string {
	const today = new Date()
	return isoDate(new Date(today.getFullYear(), today.getMonth() + 1, 1))
}

/** Whether the partner pays the customer team's usage today. */
export function isPartnerPaying(link: PartnerLink): boolean {
	const today = isoDate(new Date())
	const from = link.partner_pays_from
	const until = link.partner_pays_until
	return Boolean(from && from <= today && (!until || until >= today))
}
