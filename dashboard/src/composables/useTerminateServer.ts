import { ref, watch } from 'vue'
import { useServers, type VirtualMachineRow } from '@/composables/useServers'
import { getErrorMessage } from '@/lib/feedback'

/**
 * The terminate dialog's state. A failure keeps the dialog open with the reason inline,
 * because a toast after a destructive action is easy to miss.
 */
export function useTerminateServer(onTerminated: () => void) {
	const { runCommand } = useServers()
	const pendingTerminate = ref<VirtualMachineRow | null>(null)
	const terminateError = ref('')

	watch(pendingTerminate, () => {
		terminateError.value = ''
	})

	async function confirmTerminate(
		server: VirtualMachineRow,
		takeSnapshot: boolean,
	): Promise<void> {
		terminateError.value = ''
		try {
			await runCommand('terminate', server, {
				takeSnapshot,
				throwOnError: true,
			})
			pendingTerminate.value = null
			onTerminated()
		} catch (failure) {
			terminateError.value = getErrorMessage(
				failure,
				"We couldn't terminate this server.",
			)
		}
	}

	return { pendingTerminate, terminateError, confirmTerminate }
}
