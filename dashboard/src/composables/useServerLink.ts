import { type Ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { VirtualMachineRow } from '@/composables/useServers'
import { infoToast } from '@/lib/feedback'

export type ServerLinkAction = 'overview' | 'resize'

type ServerLinkHandlers = Record<
	ServerLinkAction,
	(server: VirtualMachineRow) => void
>

interface ServerLinkFleet {
	activeTeam: Ref<string | null | undefined>
	servers: Ref<VirtualMachineRow[]>
	reload: () => Promise<unknown>
}

/**
 * Opens what a link from a server's own dashboard asks for, such as
 * `/servers?pilot=<pilot audience>&action=resize`. An unknown action opens the overview.
 * Each link reads a fresh server list, so a cached list never decides it.
 */
export function useServerLink(
	fleet: ServerLinkFleet,
	handlers: ServerLinkHandlers,
): void {
	const route = useRoute()
	const router = useRouter()

	async function open(
		audience: string,
		action: ServerLinkAction,
	): Promise<void> {
		try {
			await fleet.reload()
		} catch {
			return // The page already shows why the list did not load.
		}
		const server = fleet.servers.value.find(
			(row) => row.pilot_audience === audience,
		)
		if (!server) {
			infoToast("This server isn't in your current team.")
			return
		}
		;(handlers[action] ?? handlers.overview)(server)
	}

	watch(
		[() => route.query.pilot, fleet.activeTeam],
		([audience, team]) => {
			if (typeof audience !== 'string' || !audience || !team) return
			const action = String(route.query.action ?? '') as ServerLinkAction
			// Drop the link so a refresh or back does not open it again.
			router.replace({ path: '/servers', query: {} })
			open(audience, action)
		},
		{ immediate: true },
	)
}
