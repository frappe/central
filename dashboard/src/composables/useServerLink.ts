import { type Ref, type WatchStopHandle, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { VirtualMachineRow } from '@/composables/useServers'
import { infoToast, isAbortError } from '@/lib/feedback'

export type ServerLinkAction = 'overview' | 'resize' | 'open-bench'

type ServerLinkHandlers = Record<
	ServerLinkAction,
	(server: VirtualMachineRow) => void
>

interface ServerLinkFleet {
	activeTeam: Ref<string | null | undefined>
	servers: Ref<VirtualMachineRow[]>
	loading: Ref<boolean>
	loaded: Ref<boolean>
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
		} catch (error) {
			// The page already shows why the list did not load.
			if (!isAbortError(error)) return
		}
		const server = await findServer(audience)
		if (!server) {
			infoToast("This server isn't in your current team.")
			return
		}
		;(handlers[action] ?? handlers.overview)(server)
	}

	// On a fresh page the team's first load and this link's reload cancel each other, and a
	// cancelled load also ends `loading`. Only a list that arrived can say the server is absent.
	function findServer(
		audience: string,
	): Promise<VirtualMachineRow | undefined> {
		return new Promise((resolve) => {
			let isDone = false
			let stop: WatchStopHandle | undefined
			stop = watch(
				[fleet.servers, fleet.loading, fleet.loaded],
				() => {
					const server = fleet.servers.value.find(
						(row) => row.pilot_audience === audience,
					)
					if (
						isDone ||
						(!server && (fleet.loading.value || !fleet.loaded.value))
					)
						return
					isDone = true
					stop?.()
					resolve(server)
				},
				{ immediate: true },
			)
			if (isDone) stop()
		})
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
