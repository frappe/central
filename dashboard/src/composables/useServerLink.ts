import { type Ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { VirtualMachineRow } from '@/composables/useServers'
import { infoToast } from '@/lib/feedback'

export type ServerLinkAction = 'overview' | 'resize'

type ServerLinkHandlers = Record<
	ServerLinkAction,
	(server: VirtualMachineRow) => void
>

/**
 * Opens what a link from a server's own dashboard asks for, such as
 * `/servers?pilot=<pilot audience>&action=resize`. An unknown action opens the overview.
 */
export function useServerLink(
	servers: Ref<VirtualMachineRow[]>,
	loaded: Ref<boolean>,
	handlers: ServerLinkHandlers,
): void {
	const route = useRoute()
	const router = useRouter()
	const audience =
		typeof route.query.pilot === 'string' ? route.query.pilot : ''
	const action = String(route.query.action ?? '') as ServerLinkAction
	if (!audience) return

	let handled = false
	watch(
		loaded,
		(isLoaded) => {
			if (!isLoaded || handled) return
			handled = true
			// Drop the link so a refresh or back does not open the dialog again.
			router.replace({ path: '/servers', query: {} })

			const server = servers.value.find(
				(row) => row.pilot_audience === audience,
			)
			if (!server) {
				infoToast("This server isn't in your current team.")
				return
			}
			;(handlers[action] ?? handlers.overview)(server)
		},
		{ immediate: true },
	)
}
