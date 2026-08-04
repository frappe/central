import { ref } from 'vue'
import { errorToast, successToast } from '@/lib/toast'

// Shared "one mutation at a time" pattern for row-scoped actions: `busy` holds
// the key (user id, invitation name, ...) of the row in flight so it alone
// shows a spinner, cleared once the call settles either way.
export function useBusyRunner() {
	const busy = ref<string>('')

	async function run(
		fn: () => Promise<unknown>,
		ok: string,
		key: string,
		onSuccess?: () => void,
	): Promise<void> {
		busy.value = key
		try {
			await fn()
			successToast(ok)
			onSuccess?.()
		} catch (e) {
			errorToast(e)
		} finally {
			busy.value = ''
		}
	}

	return { busy, run }
}
