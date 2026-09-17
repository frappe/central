import { call, frappeRequest } from 'frappe-ui'
import { onBeforeUnmount, type Ref, ref, watch } from 'vue'
import { getErrorMessage } from '@/lib/toast'
import type { ActionStatus } from '@/types/serverCreation'

interface SavedCreation {
	endpoint: string
	values: Record<string, unknown>
	key: string
	action?: string
}

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

export function useProvisioningAction(team: Ref<string | null>) {
	const action = ref<ActionStatus | null>(null)
	const pending = ref<SavedCreation | null>(null)
	const submitting = ref(false)
	const checking = ref(false)
	const lastCheckedAt = ref<Date | null>(null)
	// No automatic read is scheduled and the outcome is not final: only a person can move it.
	const stalled = ref(false)
	const error = ref('')
	let timer: ReturnType<typeof setTimeout> | undefined
	let generation = 0
	let checks = 0

	function storageKey() {
		return `central-create:${team.value}`
	}

	async function refresh() {
		if (!action.value) return
		const current = generation
		const name = action.value.action
		clearTimeout(timer)
		checks += 1
		checking.value = true
		try {
			const result = await frappeRequest<ActionStatus>({
				url: '/api/method/central.api.servers.action_status',
				method: 'GET',
				params: { name },
			})
			if (current !== generation) return
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

	async function submit(endpoint: string, values: Record<string, unknown>) {
		if (
			submitting.value ||
			action.value ||
			!team.value ||
			values.team !== team.value
		)
			return
		const current = generation
		const key = storageKey()
		submitting.value = true
		error.value = ''
		try {
			// Keep the original payload after a lost reply; edited fields must not create a second VM.
			const request = pending.value ?? {
				endpoint,
				values,
				key: crypto.randomUUID(),
			}
			sessionStorage.setItem(key, JSON.stringify(request))
			pending.value = request
			const result = await call<ActionStatus>(request.endpoint, {
				...request.values,
				request_key: request.key,
			})
			if (current !== generation) return
			action.value = result
			pending.value = { ...request, action: result.action }
			sessionStorage.setItem(key, JSON.stringify(pending.value))
			await refresh()
		} catch (failure) {
			if (current !== generation) return
			const rejected = failure as { status?: number; exc_type?: string }
			if (
				[403, 417].includes(rejected.status ?? 0) &&
				['ValidationError', 'PermissionError'].includes(rejected.exc_type ?? '')
			) {
				pending.value = null
				sessionStorage.removeItem(key)
			}
			error.value = getErrorMessage(failure)
		} finally {
			if (current === generation) submitting.value = false
		}
	}

	/** Forget a finished request so the form can send a new one. An Uncertain outcome is
	 *  never cleared here: its VM may exist, and a second create would duplicate it. */
	function reset() {
		if (
			!action.value ||
			!['Succeeded', 'Failed', 'Timed Out'].includes(action.value.status)
		)
			return
		clearTimeout(timer)
		sessionStorage.removeItem(storageKey())
		action.value = null
		pending.value = null
		error.value = ''
		stalled.value = false
		lastCheckedAt.value = null
		checks = 0
	}

	/** Re-send a request whose reply was lost, under its original key, so the region
	 *  returns the same action instead of building a second server. */
	async function resume() {
		if (pending.value)
			await submit(pending.value.endpoint, pending.value.values)
	}

	watch(
		team,
		() => {
			generation += 1
			clearTimeout(timer)
			checks = 0
			action.value = null
			pending.value = null
			submitting.value = false
			checking.value = false
			stalled.value = false
			lastCheckedAt.value = null
			error.value = ''
			if (!team.value) return
			try {
				const raw = sessionStorage.getItem(storageKey())
				if (!raw) return
				const saved = JSON.parse(raw) as SavedCreation
				if (
					!saved ||
					typeof saved.key !== 'string' ||
					![
						'central.api.servers.create_server',
						'central.api.servers.create_composed_server',
					].includes(saved.endpoint) ||
					saved.values?.team !== team.value
				)
					throw new Error(
						'Saved server request is invalid. Contact support before creating another server.',
					)
				pending.value = saved
				if (saved.action) {
					action.value = {
						action: saved.action,
						status: 'Queued',
						resource_id: null,
						title: String(saved.values.title ?? ''),
						error: null,
					}
					void refresh()
				}
			} catch (failure) {
				error.value = getErrorMessage(failure)
			}
		},
		{ immediate: true },
	)

	onBeforeUnmount(() => {
		generation += 1
		clearTimeout(timer)
	})
	return {
		action,
		pending,
		submitting,
		checking,
		lastCheckedAt,
		stalled,
		error,
		submit,
		resume,
		refresh,
		reset,
	}
}
