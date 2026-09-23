import { call, frappeRequest } from 'frappe-ui'
import { onBeforeUnmount, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { getErrorMessage } from '@/lib/feedback'
import type { ActionStatus } from '@/types/serverCreation'

// Central has no push channel for action state yet, so the page polls: quickly while a
// fresh request is moving, then slowly, and it stops rather than poll forever.
const FAST_CHECKS = 20
const FAST_INTERVAL = 3_000
const SLOW_INTERVAL = 10_000
const MAX_CHECKS = 100
// Statuses that will never change again on their own.
const FINAL = ['Succeeded', 'Failed']
// Statuses no further read can advance, though the remote outcome stays open.
const SETTLED = [...FINAL, 'Uncertain', 'Timed Out']

/** Drive one server creation from the Resource Action that holds it.
 *
 *  Central saves the request before it calls a region, so the record is the only thing
 *  the browser has to remember: `openAction` is the request Central already holds for
 *  this user, and adopting it is what makes a reload, a second tab and a lost reply all
 *  land on the same request instead of starting a second one. */
export function useProvisioningAction(
	team: Ref<string | null>,
	openAction: Ref<ActionStatus | null>,
) {
	const action = ref<ActionStatus | null>(null)
	const submitting = ref(false)
	const checking = ref(false)
	const lastCheckedAt = ref<Date | null>(null)
	// No automatic read is scheduled and the outcome is not final: only a person can move it.
	const stalled = ref(false)
	const error = ref('')
	let timer: ReturnType<typeof setTimeout> | undefined
	let generation = 0
	let checks = 0

	async function refresh() {
		if (!action.value) return
		const current = generation
		const name = action.value.action
		clearTimeout(timer)
		checks += 1
		checking.value = true
		try {
			const result = await frappeRequest<ActionStatus>({
				url: methodV1(API.actionStatus),
				method: 'GET',
				params: { name },
			})
			if (current !== generation) return
			// A read this code cannot understand must not erase the request on screen.
			// Treat it as a failed read, which keeps the panel and says so.
			if (!result?.status)
				throw new Error('Central returned no status for this request.')
			action.value = result
			error.value = ''
		} catch (failure) {
			if (current !== generation) return
			error.value = getErrorMessage(
				failure,
				'Progress could not be read just now. The server may still be building.',
			)
		} finally {
			if (current === generation) {
				checking.value = false
				lastCheckedAt.value = new Date()
			}
		}
		scheduleNextCheck()
	}

	function scheduleNextCheck() {
		const status = action.value?.status
		if (!status) return
		const open = !SETTLED.includes(status)
		if (open && checks < MAX_CHECKS) {
			stalled.value = false
			timer = setTimeout(
				refresh,
				checks < FAST_CHECKS ? FAST_INTERVAL : SLOW_INTERVAL,
			)
			return
		}
		stalled.value = !FINAL.includes(status)
	}

	/** Watch a request that is already running, and start the clock on it. */
	function follow(found: ActionStatus) {
		clearTimeout(timer)
		checks = 0
		action.value = found
		error.value = ''
		stalled.value = false
		lastCheckedAt.value = new Date()
		scheduleNextCheck()
	}

	async function submit(endpoint: string, values: Record<string, unknown>) {
		if (
			submitting.value ||
			action.value ||
			!team.value ||
			values.team !== team.value
		)
			return
		const current = generation
		submitting.value = true
		error.value = ''
		try {
			const result = await call<ActionStatus>(endpoint, {
				...values,
				request_key: crypto.randomUUID(),
			})
			if (current !== generation) return
			action.value = result
			await refresh()
		} catch (failure) {
			if (current !== generation) return
			error.value = getErrorMessage(failure)
		} finally {
			if (current === generation) submitting.value = false
		}
	}

	/** Send this same request again. Central re-drives its own record, so a retry cannot
	 *  become a second server: it is refused once a region has accepted a machine. */
	async function retry() {
		if (!action.value || submitting.value) return
		const current = generation
		const name = action.value.action
		submitting.value = true
		error.value = ''
		try {
			const result = await call<ActionStatus>(API.retryAction, { name })
			if (current !== generation) return
			follow(result)
		} catch (failure) {
			if (current !== generation) return
			error.value = getErrorMessage(failure)
		} finally {
			if (current === generation) submitting.value = false
		}
	}

	/** Put a finished request out of the way, so the form comes back. */
	function reset() {
		if (
			!action.value ||
			!['Succeeded', 'Failed', 'Timed Out'].includes(action.value.status)
		)
			return
		clearTimeout(timer)
		action.value = null
		error.value = ''
		stalled.value = false
		lastCheckedAt.value = null
		checks = 0
	}

	watch(team, () => {
		generation += 1
		clearTimeout(timer)
		checks = 0
		action.value = null
		submitting.value = false
		checking.value = false
		stalled.value = false
		lastCheckedAt.value = null
		error.value = ''
	})

	// Central is the authority on what is still running, so its answer wins on arrival,
	// but never over a request this page is already watching.
	watch(
		openAction,
		(found) => {
			if (found && found.action !== action.value?.action) follow(found)
		},
		{ immediate: true },
	)

	onBeforeUnmount(() => {
		generation += 1
		clearTimeout(timer)
	})
	return {
		action,
		submitting,
		checking,
		lastCheckedAt,
		stalled,
		error,
		submit,
		retry,
		refresh,
		reset,
	}
}
