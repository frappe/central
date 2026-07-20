<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Spinner } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import CreateTeamDialog from '@/components/team/CreateTeamDialog.vue'
import MapMessageCard from '@/components/servers/MapMessageCard.vue'
import ServerOnboarding from '@/components/servers/ServerOnboarding.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
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
	specLine,
	statusVisual,
	type MapPin,
	type MapSpot,
	type ServerVisual,
} from '@/lib/serverMap'
import type { AssetRow } from '@/composables/useServers'
import type { Region } from '@/types/Central/Region'
import type { ServerRow } from '@/components/servers/ServerListPanel.vue'

// The servers page: the world map is the list (FC V2). The Asset mirror feeds
// pins; Active Atlas Instances feed empty-region + spots; a slide-in panel
// carries the searchable row list. Lifecycle actions reuse useServers so the
// map page and the ⋯ menus share one command path.

const router = useRouter()

const { assets, loading, error, reload } = useServerMapData()
const { regions } = useRegions()
const { canPowerServer, canTerminateServer, canOpenServer, canCreateServer } =
	useCapabilities()
// Actions only — list reads come from useServerMapData (unpaginated, map-shaped).
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

// A user in no team can't own servers/billing/regions — offer team creation
// instead of the (empty, error-prone) map until a team exists.
const { activeTeam, loading: sessionLoading } = useSession()
const createTeamOpen = ref(false)
const hasNoTeam = computed(() => !sessionLoading.value && !activeTeam.value)

// First-run onboarding nudge — shown until the team has a server or the user
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

// — Rows: every non-terminated server, decorated for display. A server whose
//   region is unlisted (Draining/Disabled instance) or unplaced (no coords)
//   still rows here — it just can't pin on the map. (ServerRow type lives with
//   the panel that renders it.)
const regionsByName = computed(
	() => new Map(regions.value.map((r) => [r.region, r])),
)

const rows = computed<ServerRow[]>(() =>
	assets.value.map((asset) => {
		const region = regionsByName.value.get(asset.cluster)
		return {
			id: asset.resource_id,
			name: asset.title || asset.resource_id,
			asset,
			visual: statusVisual(asset),
			specs: specLine(asset),
			region,
			regionLabel: region ? regionLabel(region) : asset.cluster,
			flag: flagEmoji(region?.country_code),
			provider: region?.provider || null,
		}
	}),
)

// — Filters. Status and region scope the map and the panel; search only
//   narrows the panel rows.
const statusOptions = computed(() => [
	{ label: 'All statuses', value: '' },
	...STATUS_FILTERS.map((s) => ({ label: s.label, value: s.key })),
])
const statusDot = computed(
	() =>
		STATUS_FILTERS.find((s) => s.key === statusFilter.value)?.dot ||
		'var(--ink-gray-4)',
)

// Regions grouped by provider for the nested menu. Providerless instances
// group under "Other" so nothing disappears from the filter.
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

// Flat option list for the Select: "All <provider> regions" rows stand in for
// the old nested provider menu. Selection is encoded as '' | 'p:<provider>' |
// 'r:<provider>|<region>' and mapped onto regionFilter.
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
		if (
			regionFilter.value.region &&
			row.asset.cluster !== regionFilter.value.region
		)
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

// — Map data. Pins carry everything their hover card shows so ServerMap stays
//   purely presentational. Only placed regions pin (0/0 = unplaced).
const pins = computed<MapPin[]>(() =>
	filtered.value
		.filter((row) => row.region && hasMapCoords(row.region))
		.map((row) => ({
			id: row.id,
			name: row.name,
			lat: row.region!.latitude!,
			lng: row.region!.longitude!,
			provider: row.provider,
			visual: row.visual,
			regionLabel: row.regionLabel,
			flag: row.flag,
			specs: row.specs,
			publicIpv4: row.asset.public_ipv4 ?? null,
			plan: row.asset.plan ?? null,
			frappeVersion: row.asset.frappe_version ?? null,
			server: row.asset,
		})),
)

// Regions with no servers show as + spots — everywhere you could deploy next.
// The status filter doesn't change what "empty" means, but a region filter
// scopes the offer too. No server:create, no offer.
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
function focusRow(row: ServerRow): void {
	mapRef.value?.focusPin(row.id)
}
function goNewServer(region: string): void {
	router.push({ path: '/servers/new', query: { region } })
}
// Closing the panel drops the spot filter with it.
watch(panelOpen, (isOpen) => {
	if (!isOpen) locationFilter.value = null
})

// — Commands. useServers reloads its own (reportview) list after each verb;
//   the map reads through registry, so reload that too after every action.
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

// Terminate confirmation — the only destructive, irreversible action.
const pendingTerminate = ref<AssetRow | null>(null)
async function confirmTerminate(server: AssetRow): Promise<void> {
	pendingTerminate.value = null
	await withReload(terminate(server))
}

// Resize a server (preset or custom) — the backend power-cycles the VM as needed, so
// this is one action with no separate stop step.
const pendingResize = ref<AssetRow | null>(null)
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
				@new-server="goNewServer"
				@cluster-open="onClusterOpen"
			>
				<template #card-actions="{ server }">
					<ServerRowActions
						:server="server"
						:can-open="canOpenServer"
						:can-power="canPowerServer"
						:can-terminate="canTerminateServer"
						:busy="busy === server.resource_id"
						:opening="opening === server.resource_id"
						@open="open"
						@start="doStart"
						@stop="doStop"
						@resize="pendingResize = $event"
						@terminate="pendingTerminate = $event"
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
				:status-dot="statusDot"
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
				@open="open"
				@start="doStart"
				@stop="doStop"
				@resize="pendingResize = $event"
				@terminate="pendingTerminate = $event"
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
			<!-- First-run onboarding: a dismissible nudge toward the one right action.
           Only while the team has no servers, and stays gone once dismissed. -->
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

		<ResizeServerDialog v-model:server="pendingResize" @resized="reloadAll" />
		<CreateTeamDialog v-model:open="createTeamOpen" />
	</div>
</template>
