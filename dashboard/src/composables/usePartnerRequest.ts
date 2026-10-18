import { useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { getErrorMessage } from '@/lib/feedback'
import type { PartnerRequest } from '@/types/api'

/** What the customer's setup page asks them to do next. */
export type PartnerRequestStep =
	| 'loading'
	| 'invalid'
	| 'closed'
	| 'sign-in'
	| 'sign-up'
	| 'wrong-account'
	| 'opening'

const DASHBOARD_HOME = '/dashboard/servers'

/** The request behind a customer's setup link from Connect. Once the right user is
 *  signed in, the console opens and its onboarding dialog asks for the answer. */
export function usePartnerRequest(token: string) {
	const { currentUser, logout } = useAuth()
	const busy = ref(false)
	const error = ref('')

	const requestCall = useCall<PartnerRequest, { token: string }>({
		url: method(API.getPartnerRequest),
		params: { token },
	})
	const request = computed(() => requestCall.data ?? null)

	const step = computed<PartnerRequestStep>(() => {
		if (requestCall.loading && !request.value) return 'loading'
		if (!request.value) return 'invalid'
		if (request.value.status !== 'Requested') return 'closed'
		if (!currentUser.value)
			return request.value.has_account ? 'sign-in' : 'sign-up'
		return currentUser.value === request.value.email
			? 'opening'
			: 'wrong-account'
	})

	// Reload, so the console boots with the session and finds the request.
	watch(step, (current) => {
		if (current === 'opening') window.location.replace(DASHBOARD_HOME)
	})

	const authQuery = computed(() =>
		new URLSearchParams({
			email: request.value?.email ?? '',
			'redirect-to': `/dashboard/connect/customer/${token}`,
		}).toString(),
	)

	async function switchAccount() {
		busy.value = true
		error.value = ''
		try {
			await logout()
			window.location.reload()
		} catch (exception) {
			error.value = getErrorMessage(exception, "We couldn't sign you out.")
		} finally {
			busy.value = false
		}
	}

	return {
		request,
		step,
		loadError: computed(() =>
			getErrorMessage(
				requestCall.error,
				'Open the link again from your project on Connect.',
			),
		),
		signInPath: computed(() => `/login?${authQuery.value}`),
		signUpPath: computed(() => `/signup?${authQuery.value}`),
		busy,
		error,
		switchAccount,
	}
}
