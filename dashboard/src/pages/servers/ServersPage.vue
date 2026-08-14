<script setup lang="ts">
import { Button, Spinner, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { API, method } from '@/api/methods'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import MapHealthStrips from '@/components/servers/MapHealthStrips.vue'
import MapMessageCard from '@/components/servers/MapMessageCard.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import ServerFilters from '@/components/servers/ServerFilters.vue'
import ServerListPanel from '@/components/servers/ServerListPanel.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerOnboarding from '@/components/servers/ServerOnboarding.vue'
import ServerOverviewDialog from '@/components/servers/ServerOverviewDialog.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import SiteRowActions from '@/components/servers/SiteRowActions.vue'
import CreateTeamDialog from '@/components/team/CreateTeamDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useFleetRows } from '@/composables/useFleetRows'
import { useRegions } from '@/composables/useRegions'
import { useServerMapData } from '@/composables/useServerMapData'
import type { AssetRow } from '@/composables/useServers'
import { useServers } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import {
	flagEmoji,
	hasMapCoords,
	type MapPin,
	type MapSpot,
	type ResourceRow,
	regionLabel,
	type ServerVisual,
	STATUS_FILTERS,
} from '@/lib/serverMap'
import { errorToast, successToast } from '@/lib/toast'
import type { Region } from '@/types/Central/Region'
import signingInHtml from './signing-in.html?raw'

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
	immediate: false,
	method: 'POST',
})

const getSiteCall = useCall<
	{ url: string | null; login_url: string | null },
	{ name: string }
>({
	url: method(API.getSite),
	immediate: false,
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

// Servers and sites decorated into one sorted ResourceRow list (useFleetRows).
const { rows } = useFleetRows(assets, sites, regions)

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

// — Wiring. Pin / cluster-row clicks go straight to the live site or server.
//   If the side panel is open, keep its location filter in step.
function canOpenBench(server: AssetRow): boolean {
	return (
		canOpenServer.value && server.status === 'Running' && !!server.gateway_url
	)
}
function openResource(row: ResourceRow): void {
	if (row.kind === 'site') {
		if (canOpenServer.value && row.site?.url) openSite(row.site.name)
		return
	}
	if (!row.asset) return
	if (canOpenBench(row.asset)) {
		open(row.asset)
		return
	}
	// Not openable yet (still provisioning, stopped, …) — show the overview.
	overviewServer.value = row.asset
}
function onOpen(id: string): void {
	const row = rows.value.find((r) => r.id === id)
	if (!row) return
	if (panelOpen.value) {
		locationFilter.value = { ids: [id], label: row.name }
	}
	openResource(row)
}
function onClusterOpen(payload: { ids: string[]; label: string }): void {
	if (panelOpen.value) locationFilter.value = payload
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

// — Sites. Open logs in: fetch a fresh login_url (Central mints a session on read),
// opening the tab synchronously so it isn't popup-blocked (with a signing-in page so
// it isn't a blank white screen during the round-trip). Terminate tears down the VM.
const openingSite = ref<string | null>(null)
async function openSite(name: string): Promise<void> {
	if (openingSite.value) return // one open at a time — no duplicate tabs/session mints
	openingSite.value = name
	// Open the signing-in page from a blob URL (no deprecated document.write, and a
	// synchronous window.open isn't popup-blocked), then point the tab at the real
	// session URL once it resolves.
	const loadingUrl = URL.createObjectURL(
		new Blob([signingInHtml], { type: 'text/html' }),
	)
	const tab = window.open(loadingUrl, '_blank')
	try {
		await getSiteCall.submit({ name })
		if (getSiteCall.error) throw getSiteCall.error
		const url = getSiteCall.data?.login_url || getSiteCall.data?.url
		if (url && tab) tab.location.href = url
		else if (url) window.location.href = url
		else {
			tab?.close()
			errorToast(
				undefined,
				"Couldn't open the site — it may not be ready yet. Try again in a moment.",
			)
		}
	} catch (e) {
		tab?.close()
		errorToast(e)
	} finally {
		URL.revokeObjectURL(loadingUrl)
		openingSite.value = null
	}
}
const pendingSiteTerminate = ref<{ name: string } | null>(null)
async function confirmSiteTerminate(): Promise<void> {
	const name = pendingSiteTerminate.value?.name
	pendingSiteTerminate.value = null
	if (!name) return
	try {
		await terminateSiteCall.submit({ name })
		successToast('Site scheduled for termination.')
		reload()
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<div class="flex h-full flex-col">
		<Teleport defer to="#header-actions">
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
		</Teleport>

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
				class="absolute inset-0"
				:pins="pins"
				:spots="spots"
				:highlight-id="hoverId"
				:allow-create="canCreateServer"
				:allow-open="canOpenServer"
				:opening-site="openingSite"
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
						:busy="openingSite === pin.site.name"
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
				:opening-site="openingSite"
				@open-row="openResource"
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
				icon-class="text-ink-red-4"
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

		<ConfirmDialog
			v-model:target="pendingTerminate"
			title="Terminate server"
			confirm-label="Yes, terminate"
			theme="red"
			:loading="busy === pendingTerminate?.resource_id"
			@confirm="confirmTerminate"
		>
			<p class="text-p-base text-ink-gray-7">
				Permanently destroy
				<span class="font-semibold text-ink-gray-9"
					>{{ pendingTerminate?.title || pendingTerminate?.resource_id }}</span
				>? This can't be undone.
			</p>
		</ConfirmDialog>

		<ConfirmDialog
			v-model:target="pendingSiteTerminate"
			title="Terminate site"
			confirm-label="Yes, terminate"
			theme="red"
			:loading="terminateSiteCall.loading"
			@confirm="confirmSiteTerminate"
		>
			<p class="text-p-base text-ink-gray-7">
				Terminate
				<span class="font-semibold text-ink-gray-9"
					>{{ pendingSiteTerminate?.name }}</span
				>? This permanently deletes the site and its backing VM. This can't be
				undone.
			</p>
		</ConfirmDialog>

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
