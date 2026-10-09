import type { Ref } from 'vue'
import { useRouter } from 'vue-router'
import type { SiteRow } from '@/composables/useServerMapData'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useServers } from '@/composables/useServers'
import type { ResourceRow } from '@/lib/serverMap'

export function useServerNavigation(
	rows: Ref<ResourceRow[]>,
	sites: Ref<SiteRow[]>,
) {
	const router = useRouter()
	const { openBench, openSite } = useServers()

	const showServer = (server: VirtualMachineRow): void => {
		router.push({ name: 'Server', params: { id: server.resource_id } })
	}

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
		if (row.server) showServer(row.server)
	}

	function openById(id: string): void {
		const row = rows.value.find((candidate) => candidate.id === id)
		if (row) openResource(row)
	}

	return {
		siteFor,
		showServer,
		openServer,
		openResource,
		openById,
		openBench,
		openSite,
	}
}
