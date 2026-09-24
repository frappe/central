import { computed, ref } from 'vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useFleetRows } from '@/composables/useFleetRows'
import { useRegions } from '@/composables/useRegions'
import { useServerMapData } from '@/composables/useServerMapData'
import { useSession } from '@/composables/useSession'
import {
	flagEmoji,
	hasMapCoords,
	type MapPin,
	type MapSpot,
	regionLabel,
	type ServerVisual,
	STATUS_FILTERS,
} from '@/lib/serverMap'

export function useServerFleet() {
	const fleet = useServerMapData()
	const { regions } = useRegions()
	const capabilities = useCapabilities()
	const session = useSession()
	const { rows } = useFleetRows(fleet.servers, fleet.sites, regions)

	const query = ref('')
	const statusFilter = ref<ServerVisual['key'] | ''>('')
	const regionFilter = ref({ provider: '', region: '' })
	const locationFilter = ref<{ ids: string[]; label: string } | null>(null)

	const statusOptions = computed(() => [
		{ label: 'All statuses', value: '', dot: 'var(--ink-gray-4)' },
		...STATUS_FILTERS.map((status) => ({
			label: status.label,
			value: status.key,
			dot: status.dot,
		})),
	])

	const placeableRegions = computed(() =>
		regions.value
			.filter(
				(region) =>
					region.display_name?.trim() &&
					region.country_code &&
					hasMapCoords(region) &&
					region.display_name !== region.region,
			)
			.slice()
			.sort((left, right) =>
				regionLabel(left).localeCompare(regionLabel(right)),
			),
	)

	const regionOptions = computed(() => [
		{ label: 'All regions', value: '' },
		...placeableRegions.value.map((region) => ({
			label: `${flagEmoji(region.country_code)} ${regionLabel(region)}`.trim(),
			value: `r:${region.provider || ''}|${region.region}`,
		})),
	])

	const regionSelection = computed({
		get(): string {
			const { provider, region } = regionFilter.value
			if (!provider && !region) return ''
			return region ? `r:${provider}|${region}` : `p:${provider}`
		},
		set(value: string) {
			if (!value) {
				regionFilter.value = { provider: '', region: '' }
				return
			}
			if (value.startsWith('p:')) {
				regionFilter.value = { provider: value.slice(2), region: '' }
				return
			}
			const [provider = '', region = ''] = value.slice(2).split('|')
			regionFilter.value = { provider, region }
		},
	})

	const filteredRows = computed(() =>
		rows.value.filter((row) => {
			if (
				regionFilter.value.provider &&
				(row.provider || 'Other') !== regionFilter.value.provider
			)
				return false
			if (
				regionFilter.value.region &&
				row.cluster !== regionFilter.value.region
			)
				return false
			if (statusFilter.value && row.visual.key !== statusFilter.value)
				return false
			return true
		}),
	)

	const panelRows = computed(() => {
		const ids = locationFilter.value?.ids
		const visible = ids
			? filteredRows.value.filter((row) => ids.includes(row.id))
			: filteredRows.value
		const term = query.value.trim().toLowerCase()
		if (!term) return visible
		return visible.filter((row) =>
			`${row.name} ${row.id} ${row.regionLabel} ${row.provider ?? ''}`
				.toLowerCase()
				.includes(term),
		)
	})

	const pillLabel = computed(() => {
		const filtered =
			statusFilter.value ||
			regionFilter.value.provider ||
			regionFilter.value.region
		return filtered ? 'Servers' : 'All servers'
	})

	const pins = computed<MapPin[]>(() =>
		filteredRows.value
			.filter((row) => row.region && hasMapCoords(row.region))
			.map((row) => {
				const base = {
					id: row.id,
					name: row.name,
					lat: row.region!.latitude!,
					lng: row.region!.longitude!,
					provider: row.provider,
					visual: row.visual,
					cluster: row.cluster,
					regionLabel: row.regionLabel,
					flag: row.flag,
					specs: row.specs,
				}
				const machine = row.server
					? {
							publicIpv4: row.server.public_ipv4 ?? null,
							plan: row.server.plan ?? null,
							frappeVersion: row.server.frappe_version ?? null,
							server: row.server,
						}
					: {}
				return row.kind === 'server'
					? { ...base, kind: 'server' as const, ...machine }
					: { ...base, kind: 'site' as const, site: row.site!, ...machine }
			}),
	)

	const spots = computed<MapSpot[]>(() => {
		if (!capabilities.canCreateServer.value) return []
		const occupied = new Set(fleet.servers.value.map((server) => server.region))
		return regions.value
			.filter((region) => !occupied.has(region.region) && hasMapCoords(region))
			.filter(
				(region) =>
					!regionFilter.value.provider ||
					(region.provider || 'Other') === regionFilter.value.provider,
			)
			.filter(
				(region) =>
					!regionFilter.value.region ||
					region.region === regionFilter.value.region,
			)
			.map((region) => ({
				id: region.region,
				lat: region.latitude!,
				lng: region.longitude!,
				provider: region.provider || null,
				regionLabel: regionLabel(region),
				flag: flagEmoji(region.country_code),
			}))
	})

	return {
		...fleet,
		...capabilities,
		activeTeam: session.activeTeam,
		sessionLoading: session.loading,
		rows,
		query,
		statusFilter,
		regionSelection,
		locationFilter,
		statusOptions,
		regionOptions,
		filteredRows,
		panelRows,
		pillLabel,
		pins,
		spots,
	}
}
