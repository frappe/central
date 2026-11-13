// After Central closed an open card setup or top-up, ask it how long the customer must
// wait. The call only reads, so it never opens a new setup or top-up.

import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { getErrorMessage } from '@/lib/feedback'

interface SetupWait {
	message: string | null
	seconds: number | null
}

export function useSetupWait() {
	const wait = useCall<SetupWait, { team: string }>({
		url: method(API.setupWait),
		immediate: false,
	})

	// The wait, said by the server; `startAgain` when there is none left.
	async function closedAttemptMessage(
		team: string,
		startAgain: string,
	): Promise<string> {
		try {
			await wait.submit({ team })
			return wait.data?.message || startAgain
		} catch (e) {
			return getErrorMessage(e, startAgain)
		}
	}

	return { closedAttemptMessage }
}
