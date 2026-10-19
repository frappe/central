import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { getErrorMessage } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type { LinkPartner, PartnerSetupTeam } from '@/types/api'

/** What the partner setup page asks the customer to do next. */
export type PartnerSetupStep =
	| 'loading'
	| 'invalid'
	| 'welcome'
	| 'name-team'
	| 'pick-team'
	| 'payer'
	| 'done'

export type PartnerPayer = 'customer' | 'partner'

/** What a partner setup link carries: `p`, the hash of the partner's code, and, when the
 *  sending site says so, the customer's company name. */
export interface PartnerSetupLink {
	p: string
	company: string
}

type ChosenStep = Extract<
	PartnerSetupStep,
	'name-team' | 'pick-team' | 'payer' | 'done'
>

/** The partner behind a partner setup link, the customer's teams, and the request that asks
 *  the partner to work with one of them. */
export function usePartnerSetup(link: PartnerSetupLink) {
	const { isGuest } = useAuth()
	const chosenStep = ref<ChosenStep | null>(null)
	const chosenTeam = ref<string | null>(null)
	const payer = ref<PartnerPayer>('customer')
	const busy = ref(false)
	const error = ref('')

	const teamsCall = useCall<PartnerSetupTeam[], { p: string }>({
		url: method(API.myTeamsForPartner),
		params: { p: link.p },
		immediate: false,
		onSuccess: chooseFirstAvailableTeam,
	})
	const partnerCall = useCall<LinkPartner | null, { p: string }>({
		url: method(API.getPartnerForLink),
		params: { p: link.p },
		immediate: Boolean(link.p),
		onSuccess: (partner) => {
			if (partner && !isGuest.value) teamsCall.reload()
		},
	})
	const createTeamCall = useCall<{ name: string }, { team_name: string }>({
		url: method(API.createTeam),
		method: 'POST',
		immediate: false,
	})
	const requestCall = useCall<unknown, Record<string, string | number>>({
		url: method(API.requestPartnerLink),
		method: 'POST',
		immediate: false,
	})

	const partner = computed(() => partnerCall.data ?? null)
	const teams = computed(() => teamsCall.data ?? [])
	const chosen = computed(
		() => teams.value.find((team) => team.name === chosenTeam.value) ?? null,
	)

	const step = computed<PartnerSetupStep>(() => {
		if (partnerCall.loading) return 'loading'
		if (!partner.value) return 'invalid'
		if (isGuest.value) return 'welcome'
		if (!teamsCall.isFinished || teamsCall.loading) return 'loading'
		if (teamsCall.error) return 'invalid'
		return chosenStep.value ?? (teams.value.length ? 'pick-team' : 'name-team')
	})

	const here = `/dashboard/partner?${new URLSearchParams({
		p: link.p,
		...(link.company ? { company: link.company } : {}),
	})}`

	function chooseFirstAvailableTeam(loaded: PartnerSetupTeam[]) {
		if (loaded.some((team) => team.name === chosenTeam.value && team.available))
			return
		chosenTeam.value = loaded.find((team) => team.available)?.name ?? null
	}

	function goTo(next: ChosenStep) {
		error.value = ''
		chosenStep.value = next
	}

	async function run(action: () => Promise<void>, fallback: string) {
		busy.value = true
		error.value = ''
		try {
			await action()
		} catch (exception) {
			error.value = getErrorMessage(exception, fallback)
		} finally {
			busy.value = false
		}
	}

	// Calls create_team itself: useCreateTeam switches to the new team, which reloads the
	// console and would drop the customer back at the start of this page.
	const createTeam = (teamName: string) =>
		run(async () => {
			const team = await createTeamCall.submit({ team_name: teamName.trim() })
			if (createTeamCall.error || !team) throw createTeamCall.error
			await teamsCall.reload()
			chosenTeam.value = team.name
			goTo('payer')
		}, "We couldn't create your account. Try again.")

	const confirm = () =>
		run(async () => {
			if (!chosen.value) return
			await submitOrThrow(requestCall, {
				team: chosen.value.name,
				p: link.p,
				paid_by_partner: payer.value === 'partner' ? 1 : 0,
			})
			goTo('done')
		}, "We couldn't send your request. Try again.")

	return {
		partner,
		teams,
		chosen,
		chosenTeam,
		payer,
		step,
		loadError: computed(() =>
			getErrorMessage(
				partnerCall.error ?? teamsCall.error,
				'Ask your partner for a new one.',
			),
		),
		signUpPath: `/signup?${new URLSearchParams({ 'redirect-to': here })}`,
		signInPath: `/login?${new URLSearchParams({ 'redirect-to': here })}`,
		busy,
		error,
		goTo,
		createTeam,
		confirm,
	}
}
