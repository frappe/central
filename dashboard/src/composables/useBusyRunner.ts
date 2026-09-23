import { ref } from 'vue'
import { errorToast, successToast } from '@/lib/toast'

// Shared "one mutation at a time" pattern for row-scoped actions: `busy` holds
// the key (user id, invitation name, ...) of the row in flight so it alone
// shows a spinner, cleared once the call settles either way.
export function useBusyRunner() {
	const busy = ref<string>('')

	async function runOrThrow(
		fn: () => Promise<unknown>,
		ok: string | null,
		key: string,
		onSuccess?: () => void,
	): Promise<void> {
		busy.value = key
		try {
			await fn()
			if (ok) successToast(ok)
			onSuccess?.()
		} finally {
			busy.value = ''
		}
	}

	async function run(
		fn: () => Promise<unknown>,
		ok: string,
		key: string,
		onSuccess?: () => void,
	): Promise<boolean> {
		try {
			await runOrThrow(fn, ok, key, onSuccess)
			return true
		} catch (error) {
			errorToast(error)
			return false
		}
	}

	return { busy, run, runOrThrow }
}
