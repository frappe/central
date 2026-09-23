import type { Ref } from 'vue'
import type { SiteRow } from '@/composables/useServerMapData'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useServers } from '@/composables/useServers'
import type { ResourceRow } from '@/lib/serverMap'

export function useServerNavigation(
	rows: Ref<ResourceRow[]>,
	sites: Ref<SiteRow[]>,
	canViewServers: Ref<boolean>,
	overviewServer: Ref<VirtualMachineRow | null>,
) {
	const { openBench, openSite } = useServers()

	function siteFor(server: VirtualMachineRow) {
		return sites.value.find((site) => site.server === server.name)
	}

	function openServer(server: VirtualMachineRow): void {
		const site = siteFor(server)
		if (site) {
			void openSite(site.name)
			return
		}
		void openBench(server)
	}

	function openResource(row: ResourceRow): void {
		if (!row.server) return

		if (row.site) {
			if (
				canViewServers.value &&
				row.server.status === 'Running' &&
				row.site.url
			) {
				void openSite(row.site.name)
				return
			}
			overviewServer.value = row.server
			return
		}

		if (
			canViewServers.value &&
			row.server.status === 'Running' &&
			row.server.gateway_url
		) {
			void openBench(row.server)
			return
		}
		overviewServer.value = row.server
	}

	function openById(id: string): void {
		const row = rows.value.find((candidate) => candidate.id === id)
		if (row) openResource(row)
	}

	return { siteFor, openServer, openResource, openById, openBench, openSite }
}
