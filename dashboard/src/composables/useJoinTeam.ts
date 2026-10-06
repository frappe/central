import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { InvitationSummary } from '@/types/api'

/** What the join page asks the visitor to do next. */
export type JoinStep =
	| 'loading'
	| 'invalid'
	| 'closed'
	| 'accept'
	| 'wrong-account'
	| 'sign-in'
	| 'sign-up'

const DASHBOARD_HOME = '/dashboard/servers'

/** The invitation behind an emailed join link, and the actions that answer it. */
export function useJoinTeam(token: string) {
	const { currentUser, logout } = useAuth()
	const { setActiveTeam } = useSession()
	const busy = ref(false)
	const error = ref('')

	const invitationCall = useCall<InvitationSummary, { token: string }>({
		url: method(API.getInvitation),
		params: { token },
	})
	const acceptCall = useCall<{ team: string }, { invitation: string }>({
		url: method(API.acceptInvitation),
		method: 'POST',
		immediate: false,
	})
	const declineCall = useCall<unknown, { invitation: string }>({
		url: method(API.declineInvitation),
		method: 'POST',
		immediate: false,
	})
	const signUpCall = useCall<
		{ team: string },
		{ token: string; full_name: string }
	>({
		url: method(API.signUpWithInvitation),
		method: 'POST',
		immediate: false,
	})

	const invitation = computed(() => invitationCall.data ?? null)

	const step = computed<JoinStep>(() => {
		if (invitationCall.loading && !invitation.value) return 'loading'
		if (!invitation.value) return 'invalid'
		if (invitation.value.status !== 'Pending') return 'closed'
		if (currentUser.value)
			return currentUser.value === invitation.value.email
				? 'accept'
				: 'wrong-account'
		return invitation.value.has_account ? 'sign-in' : 'sign-up'
	})

	const signInPath = computed(() => {
		const query = new URLSearchParams({
			email: invitation.value?.email ?? '',
			'redirect-to': `/dashboard/join/${token}`,
		})
		return `/login?${query}`
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

	// Reload so the console boots with the new session and team.
	function openTeam(team: string) {
		setActiveTeam(team)
		window.location.replace(DASHBOARD_HOME)
	}

	const accept = () =>
		run(async () => {
			const result = await acceptCall.submit({
				invitation: invitation.value!.name,
			})
			if (acceptCall.error || !result) throw acceptCall.error
			openTeam(result.team)
		}, "We couldn't accept the invitation.")

	const decline = () =>
		run(async () => {
			await declineCall.submit({ invitation: invitation.value!.name })
			if (declineCall.error) throw declineCall.error
			await invitationCall.reload()
		}, "We couldn't decline the invitation.")

	const signUp = (fullName: string) =>
		run(async () => {
			const result = await signUpCall.submit({
				token,
				full_name: fullName.trim(),
			})
			if (signUpCall.error || !result) throw signUpCall.error
			openTeam(result.team)
		}, "We couldn't create your account.")

	const switchAccount = () =>
		run(async () => {
			await logout()
			window.location.reload()
		}, "We couldn't sign you out.")

	return {
		invitation,
		step,
		loadError: computed(() =>
			getErrorMessage(
				invitationCall.error,
				'This invitation link is not valid.',
			),
		),
		signInPath,
		busy,
		error,
		accept,
		decline,
		signUp,
		switchAccount,
	}
}
