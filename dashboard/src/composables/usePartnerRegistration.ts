import { useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { getErrorMessage } from '@/lib/feedback'
import type { PartnerRegistration, PartnerSetupTeam } from '@/types/api'

/** What the registration page asks the partner's owner to do next. */
export type PartnerRegistrationStep =
	| 'loading'
	| 'invalid'
	| 'closed'
	| 'sign-in'
	| 'sign-up'
	| 'wrong-account'
	| 'pick-team'
	| 'name-team'
	| 'done'

/** The registration behind Connect's emailed link, the owner's teams, and the call that
 *  makes one of them the partner. */
export function usePartnerRegistration(token: string) {
	const { currentUser, logout } = useAuth()
	const chosenTeam = ref<string | null>(null)
	const naming = ref(false)
	const completedTeam = ref<string | null>(null)
	const busy = ref(false)
	const error = ref('')

	const registrationCall = useCall<PartnerRegistration, { token: string }>({
		url: method(API.getPartnerRegistration),
		params: { token },
	})
	const teamsCall = useCall<PartnerSetupTeam[]>({
		url: method(API.myTeamsForRegistration),
		immediate: false,
		onSuccess: (teams) => {
			if (
				!teams.some((team) => team.name === chosenTeam.value && team.available)
			)
				chosenTeam.value = teams.find((team) => team.available)?.name ?? null
		},
	})
	const createTeamCall = useCall<{ name: string }, { team_name: string }>({
		url: method(API.createTeam),
		method: 'POST',
		immediate: false,
	})
	const completeCall = useCall<
		{ team: string; partner_name: string },
		{ token: string; team: string }
	>({
		url: method(API.completePartnerRegistration),
		method: 'POST',
		immediate: false,
	})

	const registration = computed(() => registrationCall.data ?? null)
	const teams = computed(() => teamsCall.data ?? [])
	const chosen = computed(
		() => teams.value.find((team) => team.name === chosenTeam.value) ?? null,
	)
	const isOwner = computed(
		() =>
			Boolean(currentUser.value) &&
			currentUser.value === registration.value?.email,
	)

	// The teams load only for the owner, once the link is known to be open.
	watch(
		() => isOwner.value && registration.value?.status === 'Pending',
		(ready) => {
			if (ready) teamsCall.reload()
		},
		{ immediate: true },
	)

	const step = computed<PartnerRegistrationStep>(() => {
		if (registrationCall.loading && !registration.value) return 'loading'
		if (!registration.value) return 'invalid'
		if (completedTeam.value) return 'done'
		if (registration.value.status !== 'Pending') return 'closed'
		if (!currentUser.value)
			return registration.value.has_account ? 'sign-in' : 'sign-up'
		if (!isOwner.value) return 'wrong-account'
		if (!teamsCall.isFinished || teamsCall.loading) return 'loading'
		if (teamsCall.error) return 'invalid'
		return naming.value || !teams.value.length ? 'name-team' : 'pick-team'
	})

	const authQuery = computed(() =>
		new URLSearchParams({
			email: registration.value?.email ?? '',
			'redirect-to': `/dashboard/connect/partner/${token}`,
		}).toString(),
	)

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

	function startNaming(isNaming: boolean) {
		error.value = ''
		naming.value = isNaming
	}

	// Calls create_team itself: useCreateTeam switches to the new team, which reloads the
	// console and would drop the owner back at the start of this page.
	const createTeam = (teamName: string) =>
		run(async () => {
			const team = await createTeamCall.submit({ team_name: teamName.trim() })
			if (createTeamCall.error || !team) throw createTeamCall.error
			await teamsCall.reload()
			chosenTeam.value = team.name
			naming.value = false
		}, "We couldn't create the team. Try again.")

	const complete = () =>
		run(async () => {
			if (!chosen.value) return
			const result = await completeCall.submit({
				token,
				team: chosen.value.name,
			})
			if (completeCall.error || !result) throw completeCall.error
			completedTeam.value = result.team
		}, "We couldn't save the team. Try again.")

	const switchAccount = () =>
		run(async () => {
			await logout()
			window.location.reload()
		}, "We couldn't sign you out.")

	return {
		registration,
		teams,
		chosen,
		chosenTeam,
		step,
		loadError: computed(() =>
			getErrorMessage(
				registrationCall.error ?? teamsCall.error,
				'Ask Connect for a new link.',
			),
		),
		signInPath: computed(() => `/login?${authQuery.value}`),
		signUpPath: computed(() => `/signup?${authQuery.value}`),
		busy,
		error,
		startNaming,
		createTeam,
		complete,
		switchAccount,
	}
}
