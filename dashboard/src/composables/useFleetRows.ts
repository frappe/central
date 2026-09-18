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

	const assetsByName = computed(
		() => new Map(assets.value.map((asset) => [asset.name, asset])),
	)

	// One machine is one row. A site IS the machine its image was baked on, so the site
	// row carries that machine and the machine does not row again — otherwise a trial,
	// which is one site on one VM, would show up twice.
	const assetsOwnedBySite = computed(
		() => new Set(sites.value.map((site) => site.asset).filter(Boolean)),
	)

	const serverRows = computed<ResourceRow[]>(() =>
		assets.value
			.filter((asset) => !assetsOwnedBySite.value.has(asset.name))
			.map((asset) => {
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
			const asset = site.asset
				? assetsByName.value.get(site.asset)
				: undefined
			return {
				kind: 'site' as const,
				id: site.name,
				// The site's own name; the full FQDN drops to the secondary line (specs)
				// so a site reads like the VM it is, not a routing string.
				name: site.subdomain || site.name,
				// The machine it runs on, so the row keeps the power and resize actions
				// a server row has. Clicking the row still opens the site.
				asset,
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
