import { computed, type Ref } from 'vue'
import type { SiteRow } from '@/composables/useServerMapData'
import type { VirtualMachineRow } from '@/composables/useServers'
import {
	flagEmoji,
	type ResourceRow,
	regionLabel,
	siteVisual,
	specLine,
	statusVisual,
} from '@/lib/serverMap'
import type { Region } from '@/types/Region'

// Decorate the two mirrors (servers + self-serve sites) into one uniform row
// shape the map and panel render indistinguishably. A resource whose region is
// unlisted/unplaced still rows — it just can't pin. Pure: the page owns the
// filter state; this only shapes.
export function useFleetRows(
	servers: Ref<VirtualMachineRow[]>,
	sites: Ref<SiteRow[]>,
	regions: Ref<Region[]>,
) {
	const regionsByName = computed(
		() => new Map(regions.value.map((r) => [r.region, r])),
	)

	const serversByName = computed(
		() => new Map(servers.value.map((server) => [server.name, server])),
	)

	// One machine is one row. A site IS the machine its image was baked on, so the site
	// row carries that machine and the machine does not row again — otherwise a trial,
	// which is one site on one VM, would show up twice.
	const serversOwnedBySite = computed(
		() => new Set(sites.value.map((site) => site.server).filter(Boolean)),
	)

	const serverRows = computed<ResourceRow[]>(() =>
		servers.value
			.filter((server) => !serversOwnedBySite.value.has(server.name))
			.map((server) => {
				const region = regionsByName.value.get(server.region)
				return {
					kind: 'server' as const,
					id: server.resource_id,
					name: server.title || server.resource_id,
					server,
					visual: statusVisual(server),
					specs: specLine(server),
					cluster: server.region,
					region,
					regionLabel: region ? regionLabel(region) : server.region,
					flag: flagEmoji(region?.country_code),
					provider: region?.provider || null,
				}
			}),
	)

	const siteRows = computed<ResourceRow[]>(() =>
		sites.value.map((site) => {
			const region = site.region
				? regionsByName.value.get(site.region)
				: undefined
			const server = site.server
				? serversByName.value.get(site.server)
				: undefined
			return {
				kind: 'site' as const,
				id: site.name,
				// The machine's name, the same one the overview shows. The hostname is
				// where Open goes, not what the row is called.
				name: server?.title || site.subdomain || site.name,
				server,
				visual: server
					? statusVisual(server)
					: siteVisual(site.status, site.pending_action),
				specs: server ? specLine(server) : '',
				cluster: site.region ?? '',
				region,
				regionLabel: region ? regionLabel(region) : (site.region ?? ''),
				flag: flagEmoji(region?.country_code),
				provider: region?.provider ?? null,
				site: {
					name: site.name,
					url: site.url,
					pending_action: site.pending_action,
				},
			}
		}),
	)

	// One list, sorted by name — no servers-then-sites tell; a site is just another VM.
	const rows = computed<ResourceRow[]>(() =>
		[...serverRows.value, ...siteRows.value].sort((a, b) =>
			a.name.localeCompare(b.name),
		),
	)

	return { rows, serverRows, siteRows, regionsByName }
}
