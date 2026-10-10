import { ref } from 'vue'
import { useServers, type VirtualMachineRow } from '@/composables/useServers'
import { useTerminateServer } from '@/composables/useTerminateServer'

/**
 * The servers page's commands and the dialogs they open. One feed carries servers and
 * sites, so every command that changed something reloads it with `reload`.
 */
export function useFleetCommands(reload: () => void) {
	const { refreshServers, runCommand } = useServers()

	async function reloadAfter(action: Promise<boolean>): Promise<void> {
		if (await action) reload()
	}

	const pendingRestart = ref<VirtualMachineRow | null>(null)
	async function confirmRestart(server: VirtualMachineRow): Promise<void> {
		try {
			await reloadAfter(runCommand('restart', server))
		} finally {
			pendingRestart.value = null
		}
	}

	const pendingResize = ref<VirtualMachineRow | null>(null)
	const isResizeOpen = ref(false)
	function openResize(server: VirtualMachineRow): void {
		pendingResize.value = server
		isResizeOpen.value = true
	}

	return {
		refresh: () => reloadAfter(refreshServers()),
		start: (server: VirtualMachineRow) =>
			reloadAfter(runCommand('start', server)),
		stop: (server: VirtualMachineRow) =>
			reloadAfter(runCommand('stop', server)),
		pendingRestart,
		confirmRestart,
		pendingResize,
		isResizeOpen,
		openResize,
		pendingSnapshot: ref<VirtualMachineRow | null>(null),
		...useTerminateServer(reload),
	}
}
