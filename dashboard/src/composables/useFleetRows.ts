import { computed, type Ref } from 'vue'
import type { SiteRow } from '@/composables/useServerMapData'
import type { AssetRow } from '@/composables/useServers'
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
	assets: Ref<AssetRow[]>,
	sites: Ref<SiteRow[]>,
	regions: Ref<Region[]>,
) {
	const regionsByName = computed(
		() => new Map(regions.value.map((r) => [r.region, r])),
	)

	const serverRows = computed<ResourceRow[]>(() =>
		assets.value.map((asset) => {
			const region = regionsByName.value.get(asset.cluster)
			return {
				kind: 'server' as const,
				id: asset.resource_id,
				name: asset.title || asset.resource_id,
				asset,
				visual: statusVisual(asset),
				specs: specLine(asset),
				cluster: asset.cluster,
				region,
				regionLabel: region ? regionLabel(region) : asset.cluster,
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
			return {
				kind: 'site' as const,
				id: site.name,
				// The user-entered name ("demo.in"); the full FQDN drops to the secondary
				// line (specs) so a site reads like the VM it is, not a routing string.
				name: site.subdomain || site.name,
				visual: siteVisual(site.status, site.pending_action),
				specs: site.name,
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
