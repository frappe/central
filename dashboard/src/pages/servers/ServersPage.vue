<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Dialog, Spinner, useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import CreateTeamDialog from '@/components/team/CreateTeamDialog.vue'
import MapMessageCard from '@/components/servers/MapMessageCard.vue'
import ServerOnboarding from '@/components/servers/ServerOnboarding.vue'
import ServerOverviewDialog from '@/components/servers/ServerOverviewDialog.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import SiteRowActions from '@/components/servers/SiteRowActions.vue'
import TerminateDialog from '@/components/servers/TerminateDialog.vue'
import MapHealthStrips from '@/components/servers/MapHealthStrips.vue'
import ServerFilters from '@/components/servers/ServerFilters.vue'
import ServerListPanel from '@/components/servers/ServerListPanel.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useRegions } from '@/composables/useRegions'
import { useServerMapData } from '@/composables/useServerMapData'
import { useServers } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import {
	STATUS_FILTERS,
	flagEmoji,
	hasMapCoords,
	regionLabel,
	siteVisual,
	specLine,
	statusVisual,
	type MapPin,
	type MapSpot,
	type ServerVisual,
} from '@/lib/serverMap'
import type { AssetRow } from '@/composables/useServers'
import type { Region } from '@/types/Central/Region'
import type { ResourceRow } from '@/components/servers/ServerListPanel.vue'

// The servers page: the world map is the list (FC V2). Servers (the Asset mirror)
// and sites (the Site mirror — each a 1:1-backed VM) come from one feed and list
// together, indistinguishable — same provider avatar, same pin, one sorted list.
// Lifecycle actions reuse useServers so the map, panel, and ⋯ menus share one path.

const router = useRouter()

const { assets, sites, loading, error, reload } = useServerMapData()
const { regions } = useRegions()
const { canPowerServer, canTerminateServer, canOpenServer, canCreateServer } =
	useCapabilities()
// Actions only — list reads come from useServerMapData.
const {
	refreshing,
	stale,
	busy,
	opening,
	refreshAssets,
	start,
	stop,
	terminate,
	open,
} = useServers()

const terminateSiteCall = useCall<unknown, { name: string }>({
	url: method(API.terminateSite),
})

// A user in no team can't own servers/billing/regions — offer team creation
// instead of the (empty, error-prone) map until a team exists.
const { activeTeam, loading: sessionLoading } = useSession()
const createTeamOpen = ref(false)
const hasNoTeam = computed(() => !sessionLoading.value && !activeTeam.value)

// First-run onboarding nudge — shown until the team has an asset or the user
// dismisses it (remembered across visits so it never nags).
const ONBOARDING_KEY = 'central.console.serverOnboardingDismissed'
const onboardingDismissed = ref(localStorage.getItem(ONBOARDING_KEY) === '1')
const showOnboarding = computed(
	() =>
		!loading.value &&
		!rows.value.length &&
		canCreateServer.value &&
		!onboardingDismissed.value,
)
function dismissOnboarding(): void {
	onboardingDismissed.value = true
	localStorage.setItem(ONBOARDING_KEY, '1')
}

const q = ref('')
const statusFilter = ref<ServerVisual['key'] | ''>('')
const regionFilter = ref<{ provider: string; region: string }>({
	provider: '',
	region: '',
})
const hoverId = ref<string | null>(null)
const panelOpen = ref(false)
const mapRef = ref<InstanceType<typeof ServerMap> | null>(null)

const regionsByName = computed(
	() => new Map(regions.value.map((r) => [r.region, r])),
)

// — Rows: servers and sites decorated into one shape (ResourceRow). A server or
//   site whose region is unlisted/unplaced still rows here — it just can't pin.
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
		const region = site.region ? regionsByName.value.get(site.region) : undefined
		return {
			kind: 'site' as const,
			id: site.name,
			// The user-entered name ("demo.in"); the full FQDN drops to the secondary
			// line (specs) so a site reads like the VM it is, not a routing string.
			name: site.subdomain || site.name,
			visual: siteVisual(site.status),
			specs: site.name,
			cluster: site.region ?? '',
			region,
			regionLabel: region ? regionLabel(region) : (site.region ?? ''),
			flag: flagEmoji(region?.country_code),
			provider: region?.provider ?? null,
			site: { name: site.name, url: site.url },
		}
	}),
)

// One list, sorted by name — no servers-then-sites tell; a site is just another VM.
const rows = computed<ResourceRow[]>(() =>
	[...serverRows.value, ...siteRows.value].sort((a, b) =>
		a.name.localeCompare(b.name),
	),
)

// — Filters. Status and region scope the map and the panel; search only
//   narrows the panel rows.
const statusOptions = computed(() => [
	{ label: 'All statuses', value: '', dot: 'var(--ink-gray-4)' },
	...STATUS_FILTERS.map((s) => ({ label: s.label, value: s.key, dot: s.dot })),
])

const providerGroups = computed(() => {
	const groups = new Map<string, Region[]>()
	for (const region of regions.value) {
		const provider = region.provider || 'Other'
		if (!groups.has(provider)) groups.set(provider, [])
		groups.get(provider)!.push(region)
	}
	return [...groups.entries()].map(([provider, list]) => ({
		provider,
		regions: list,
	}))
})

const regionOptions = computed(() => [
	{ label: 'All regions', value: '' },
	...providerGroups.value.flatMap((group) => [
		{ label: `All ${group.provider} regions`, value: `p:${group.provider}` },
		...group.regions.map((r) => ({
			label: `${flagEmoji(r.country_code)} ${regionLabel(r)}`.trim(),
			value: `r:${group.provider}|${r.region}`,
		})),
	]),
])
const regionSelection = computed({
	get(): string {
		const { provider, region } = regionFilter.value
		if (!provider && !region) return ''
		if (!region) return `p:${provider}`
		return `r:${provider}|${region}`
	},
	set(value: string) {
		if (!value) regionFilter.value = { provider: '', region: '' }
		else if (value.startsWith('p:'))
			regionFilter.value = { provider: value.slice(2), region: '' }
		else {
			const [provider, region] = value.slice(2).split('|')
			regionFilter.value = { provider, region }
		}
	},
})

const filtered = computed(() =>
	rows.value.filter((row) => {
		if (
			regionFilter.value.provider &&
			(row.provider || 'Other') !== regionFilter.value.provider
		)
			return false
		if (regionFilter.value.region && row.cluster !== regionFilter.value.region)
			return false
		if (statusFilter.value && row.visual.key !== statusFilter.value)
			return false
		return true
	}),
)

// Clicking a map cluster narrows the panel to that spot ({ ids, label }).
const locationFilter = ref<{ ids: string[]; label: string } | null>(null)

const panelRows = computed(() => {
	let list = filtered.value
	if (locationFilter.value)
		list = list.filter((row) => locationFilter.value!.ids.includes(row.id))
	const term = q.value.trim().toLowerCase()
	if (!term) return list
	return list.filter((row) =>
		`${row.name} ${row.id} ${row.regionLabel} ${row.provider ?? ''}`
			.toLowerCase()
			.includes(term),
	)
})

const pillLabel = computed(() =>
	statusFilter.value || regionFilter.value.provider || regionFilter.value.region
		? `Servers (${filtered.value.length})`
		: `All servers (${filtered.value.length})`,
)

// — Map data. Every VM pins — servers and sites alike; a site clusters with any
//   server sharing its region, so co-located resources gather under one node. Pins
//   carry everything their hover card shows so ServerMap stays presentational.
const pins = computed<MapPin[]>(() =>
	filtered.value
		.filter(
			(row) =>
				(row.asset || row.site) && row.region && hasMapCoords(row.region),
		)
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
			return row.kind === 'server'
				? {
						...base,
						kind: 'server' as const,
						publicIpv4: row.asset!.public_ipv4 ?? null,
						plan: row.asset!.plan ?? null,
						frappeVersion: row.asset!.frappe_version ?? null,
						server: row.asset!,
					}
				: { ...base, kind: 'site' as const, site: row.site! }
		}),
)

// Regions with no servers show as + spots — everywhere you could deploy next.
const spots = computed<MapSpot[]>(() => {
	if (!canCreateServer.value) return []
	const occupied = new Set(assets.value.map((asset) => asset.cluster))
	return regions.value
		.filter((r) => !occupied.has(r.region) && hasMapCoords(r))
		.filter(
			(r) =>
				!regionFilter.value.provider ||
				(r.provider || 'Other') === regionFilter.value.provider,
		)
		.filter(
			(r) =>
				!regionFilter.value.region || r.region === regionFilter.value.region,
		)
		.map((r) => ({
			id: r.region,
			lat: r.latitude!,
			lng: r.longitude!,
			provider: r.provider || null,
			regionLabel: regionLabel(r),
			flag: flagEmoji(r.country_code),
		}))
})

// — Wiring. Pin clicks lock the card (the map owns that); if the panel is
//   showing, they also narrow it to the clicked server so both stay in step.
function onOpen(id: string): void {
	if (!panelOpen.value) return
	const row = rows.value.find((r) => r.id === id)
	locationFilter.value = { ids: [id], label: row?.name ?? id }
}
function onClusterOpen(payload: { ids: string[]; label: string }): void {
	if (panelOpen.value) locationFilter.value = payload
}
function focusRow(row: ResourceRow): void {
	mapRef.value?.focusPin(row.id)
}
function goNewServer(region: string): void {
	router.push({ path: '/servers/new', query: { region } })
}
// Closing the panel drops the spot filter with it.
watch(panelOpen, (isOpen) => {
	if (!isOpen) locationFilter.value = null
})

// — Commands. One feed carries servers and sites, so a single reload refreshes both.
function reloadAll(): void {
	reload()
}
async function withReload(action: Promise<unknown>): Promise<void> {
	await action
	reload()
}
const doRefresh = (): Promise<void> => withReload(refreshAssets())
const doStart = (server: AssetRow): Promise<void> => withReload(start(server))
const doStop = (server: AssetRow): Promise<void> => withReload(stop(server))

const pendingTerminate = ref<AssetRow | null>(null)
async function confirmTerminate(server: AssetRow): Promise<void> {
	pendingTerminate.value = null
	await withReload(terminate(server))
}

const pendingResize = ref<AssetRow | null>(null)
const overviewServer = ref<AssetRow | null>(null)
const overviewOpen = computed({
	get: () => !!overviewServer.value,
	set: (isOpen: boolean) => {
		if (!isOpen) overviewServer.value = null
	},
})

// — Sites. Open goes to the live site; terminate tears down the backing VM.
function openSite(url: string): void {
	window.open(url, '_blank', 'noopener')
}
const pendingSiteTerminate = ref<{ name: string } | null>(null)
const siteTerminateOpen = computed({
	get: () => !!pendingSiteTerminate.value,
	set: (isOpen: boolean) => {
		if (!isOpen) pendingSiteTerminate.value = null
	},
})
async function confirmSiteTerminate(): Promise<void> {
	const name = pendingSiteTerminate.value?.name
	pendingSiteTerminate.value = null
	if (!name) return
	await terminateSiteCall.submit({ name })
	reload()
}
</script>

<template>
	<div class="flex h-full flex-col">
		<PageHeader title="Servers">
			<template #actions>
				<Button
					v-if="activeTeam"
					label="Refresh"
					icon-left="lucide-refresh-cw"
					:loading="refreshing"
					@click="doRefresh"
				/>
				<!-- Hidden while the onboarding card is up — that card carries the single
             primary action then, so there's never two New-server buttons at once. -->
				<Button
					v-if="activeTeam && canCreateServer && !showOnboarding"
					variant="solid"
					label="New server"
					icon-left="lucide-plus"
					@click="$router.push('/servers/new')"
				/>
			</template>
		</PageHeader>

		<!-- No team at all: create one before anything else can be provisioned. -->
		<div v-if="hasNoTeam" class="flex flex-1 items-center justify-center p-8">
			<EmptyState
				icon="lucide-users"
				title="No team yet"
				description="Create a team before provisioning servers. The team becomes the owner boundary for permissions, billing, and Atlas resources."
			>
				<template #action>
					<Button
						variant="solid"
						label="Create team"
						icon-left="lucide-plus"
						@click="createTeamOpen = true"
					/>
				</template>
			</EmptyState>
		</div>

		<!-- The map is the page. Everything else floats above it. `isolate` keeps
         the overlays' z-indexes from leaking above body-portaled menus. -->
		<div v-else class="relative isolate flex-1 overflow-hidden">
			<ServerMap
				ref="mapRef"
				class="absolute inset-0"
				:pins="pins"
				:spots="spots"
				:highlight-id="hoverId"
				:allow-create="canCreateServer"
				:allow-open="canOpenServer"
				@open="onOpen"
				@open-server="open"
				@open-site="openSite"
				@new-server="goNewServer"
				@cluster-open="onClusterOpen"
			>
				<template #card-actions="{ pin }">
					<ServerRowActions
						v-if="pin.kind === 'server' && pin.server"
						:server="pin.server"
						:can-open="canOpenServer"
						:can-power="canPowerServer"
						:can-terminate="canTerminateServer"
						:busy="busy === pin.server.resource_id"
						:opening="opening === pin.server.resource_id"
						@overview="overviewServer = $event"
						@open="open"
						@start="doStart"
						@stop="doStop"
						@resize="pendingResize = $event"
						@terminate="pendingTerminate = $event"
					/>
					<SiteRowActions
						v-else-if="pin.site"
						:site="pin.site"
						:can-open="canOpenServer"
						:can-terminate="canTerminateServer"
						@open="openSite"
						@terminate="pendingSiteTerminate = { name: $event }"
					/>
				</template>
			</ServerMap>

			<MapHealthStrips
				:stale="stale"
				:error="error"
				:has-rows="rows.length > 0"
				@retry="reloadAll"
			/>

			<ServerFilters
				v-model:status-filter="statusFilter"
				v-model:region-selection="regionSelection"
				:status-options="statusOptions"
				:region-options="regionOptions"
			/>

			<ServerListPanel
				v-model:open="panelOpen"
				v-model:query="q"
				v-model:hover-id="hoverId"
				:pill-label="pillLabel"
				:rows="panelRows"
				:has-rows="rows.length > 0"
				:location-filter="locationFilter"
				:can-open="canOpenServer"
				:can-power="canPowerServer"
				:can-terminate="canTerminateServer"
				:busy="busy"
				:opening="opening"
				@focus-row="focusRow"
				@clear-location="locationFilter = null"
				@overview="overviewServer = $event"
				@open="open"
				@start="doStart"
				@stop="doStop"
				@resize="pendingResize = $event"
				@terminate="pendingTerminate = $event"
				@open-site="openSite"
				@terminate-site="pendingSiteTerminate = { name: $event }"
			/>

			<!-- Initial load / hard failure / first run — centered over the map -->
			<div
				v-if="loading && !rows.length"
				class="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center"
			>
				<Spinner class="size-5 text-ink-gray-5" />
			</div>
			<MapMessageCard
				v-else-if="error && !rows.length"
				icon="lucide-circle-alert"
				icon-class="text-ink-red-5"
				title="Couldn't load your servers"
				:description="error"
			>
				<template #action>
					<Button class="mt-3" label="Retry" @click="reloadAll" />
				</template>
			</MapMessageCard>
			<!-- First-run onboarding: a dismissible nudge toward the one right action. -->
			<ServerOnboarding
				v-else-if="showOnboarding"
				@create="$router.push('/servers/new')"
				@dismiss="dismissOnboarding"
			/>
		</div>

		<TerminateDialog
			v-model:server="pendingTerminate"
			:loading="busy === pendingTerminate?.resource_id"
			@confirm="confirmTerminate"
		/>

		<Dialog
			v-model="siteTerminateOpen"
title="Terminate site" size="sm" :actions="[
			{
		label: 'Yes, terminate',
		variant: 'solid',
		theme: 'red',
		loading: terminateSiteCall.loading,
		onClick: confirmSiteTerminate,
	},
]">
			<p class="text-p-base text-ink-gray-7">
				Terminate <span class="font-semibold text-ink-gray-9">{{ pendingSiteTerminate?.name }}</span>?
				This permanently deletes the site and its backing VM. This can't be undone.
			</p>
		</Dialog>

		<ResizeServerDialog v-model:server="pendingResize" @resized="reloadAll" />
		<ServerOverviewDialog
			v-model:open="overviewOpen"
			:server="overviewServer"
			:can-open="canOpenServer"
			:can-resize="canPowerServer"
			@open="open"
			@resize="pendingResize = $event"
		/>
		<CreateTeamDialog v-model:open="createTeamOpen" />
	</div>
</template>
