import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { PartnerRegistrationSummary } from '@/types/api'

/** What the partner registration page asks the visitor to do next. */
export type PartnerRegistrationStep =
	| 'loading'
	| 'invalid'
	| 'closed'
	| 'sign-in'
	| 'wrong-account'
	| 'choose-team'

const DASHBOARD_HOME = '/dashboard/servers'

/** The registration behind a link from Frappe Connect, and the action that completes it. */
export function usePartnerRegistration(token: string) {
	const { currentUser, logout } = useAuth()
	const { setActiveTeam } = useSession()
	const busy = ref(false)
	const error = ref('')

	const registrationCall = useCall<
		PartnerRegistrationSummary,
		{ token: string }
	>({
		url: method(API.getPartnerRegistration),
		params: { token },
	})
	const completeCall = useCall<
		{ team: string; return_url: string | null },
		{ token: string; team: string }
	>({
		url: method(API.completePartnerRegistration),
		method: 'POST',
		immediate: false,
	})

	const registration = computed(() => registrationCall.data ?? null)

	const step = computed<PartnerRegistrationStep>(() => {
		if (registrationCall.loading && !registration.value) return 'loading'
		if (!registration.value) return 'invalid'
		if (registration.value.status !== 'Pending') return 'closed'
		if (!currentUser.value) return 'sign-in'
		return currentUser.value === registration.value.owner_email
			? 'choose-team'
			: 'wrong-account'
	})

	// A new email signs up and an existing one signs in. Both come back here.
	const signInPath = computed(() => {
		const query = new URLSearchParams({
			email: registration.value?.owner_email ?? '',
			'redirect-to': `/dashboard/partner-registration/${token}`,
		})
		const path = registration.value?.has_account ? '/login' : '/signup'
		return `${path}?${query}`
	})

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

	const complete = (team: string) =>
		run(async () => {
			const result = await completeCall.submit({ token, team })
			if (completeCall.error || !result) throw completeCall.error
			setActiveTeam(result.team)
			window.location.replace(result.return_url || DASHBOARD_HOME)
		}, "We couldn't register the partner team.")

	const switchAccount = () =>
		run(async () => {
			await logout()
			window.location.reload()
		}, "We couldn't sign you out.")

	return {
		registration,
		step,
		loadError: computed(() =>
			getErrorMessage(
				registrationCall.error,
				'This registration link is not valid.',
			),
		),
		signInPath,
		busy,
		error,
		complete,
		switchAccount,
		reload: () => registrationCall.reload(),
	}
}
