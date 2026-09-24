<script setup lang="ts">
import { Alert, Button, Spinner } from 'frappe-ui'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import MapHealthStrips from '@/components/servers/MapHealthStrips.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import ServerFilters from '@/components/servers/ServerFilters.vue'
import ServerListPanel from '@/components/servers/ServerListPanel.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerOnboarding from '@/components/servers/ServerOnboarding.vue'
import ServerOverviewDialog from '@/components/servers/ServerOverviewDialog.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import TerminateServerDialog from '@/components/servers/TerminateServerDialog.vue'
import TakeSnapshotDialog from '@/components/snapshots/TakeSnapshotDialog.vue'
import CreateTeamDialog from '@/components/team/CreateTeamDialog.vue'
import { useServerFleet } from '@/composables/useServerFleet'
import { useServerNavigation } from '@/composables/useServerNavigation'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useServers } from '@/composables/useServers'
import { getServerActions, type ServerActions } from '@/lib/capabilities'
import { getErrorMessage } from '@/lib/feedback'

// The servers page: the world map is the list (FC V2). Servers (the Virtual Machine mirror)
// and sites (the Site mirror — each a 1:1-backed VM) come from one feed and list
// together, indistinguishable — same provider avatar, same pin, one sorted list.
// Lifecycle actions reuse useServers so the map, panel, and ⋯ menus share one path.

const router = useRouter()
const route = useRoute()

const {
	sites,
	loading,
	error,
	reload,
	canPowerServer,
	canResizeServer,
	canTerminateServer,
	canSnapshotServer,
	canViewServers,
	canCreateServer,
	activeTeam,
	sessionLoading,
	rows,
	query: q,
	statusFilter,
	regionSelection,
	locationFilter,
	statusOptions,
	regionOptions,
	panelRows,
	pillLabel,
	pins,
	spots,
} = useServerFleet()
// Actions only — list reads come from useServerMapData.
const { refreshing, stale, busy, opening, refreshServers, runCommand } =
	useServers()

// A user in no team can't own servers/billing/regions — offer team creation
// instead of the (empty, error-prone) map until a team exists.
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

const hoverId = ref<string | null>(null)
const panelOpen = ref(false)
const overviewServer = ref<VirtualMachineRow | null>(null)
const { siteFor, openServer, openResource, openById, openBench, openSite } =
	useServerNavigation(rows, sites, canViewServers, overviewServer)

// — Wiring. Pin / cluster-row clicks go straight to the live site or server.
//   If the side panel is open, keep its location filter in step.
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

// Landing straight from "Create server" (?created=<id>): open the list so the new
// server's provisioning row is visible right away, not hidden behind the collapsed pill.
const cameFromCreate =
	typeof route.query.created === 'string' && !!route.query.created

// Opening the map shows the current fleet. The feed is a shared singleton that only
// reloads on team-ready or a live event, so a server created while this page was
// unmounted (the New server flow) wouldn't be here yet — reload on every entry.
onMounted(() => {
	if (activeTeam.value) reload()
	if (cameFromCreate) {
		panelOpen.value = true
		// Drop the flag so a back/refresh doesn't reopen the panel.
		router.replace({ path: '/servers', query: {} })
	}
})

// — Commands. One feed carries servers and sites, so a single reload refreshes both.
function reloadAll(): void {
	reload()
}
async function reloadAfter(action: Promise<boolean>): Promise<void> {
	if (await action) reload()
}
const doRefresh = (): Promise<void> => reloadAfter(refreshServers())
const doStart = (server: VirtualMachineRow): Promise<void> =>
	reloadAfter(runCommand('start', server))
const doStop = (server: VirtualMachineRow): Promise<void> =>
	reloadAfter(runCommand('stop', server))
const pendingRestart = ref<VirtualMachineRow | null>(null)
async function confirmRestart(server: VirtualMachineRow): Promise<void> {
	try {
		await reloadAfter(runCommand('restart', server))
	} finally {
		pendingRestart.value = null
	}
}

const pendingTerminate = ref<VirtualMachineRow | null>(null)
const terminateError = ref('')
// Reset the inline error whenever the dialog opens on a different server or closes.
watch(pendingTerminate, () => {
	terminateError.value = ''
})
async function confirmTerminate(
	server: VirtualMachineRow,
	takeSnapshot: boolean,
): Promise<void> {
	terminateError.value = ''
	try {
		// Destructive: keep the dialog open and show the reason inline on failure, rather
		// than closing and firing a toast the user may miss. The row then shows "Terminating…".
		await runCommand('terminate', server, {
			takeSnapshot,
			throwOnError: true,
		})
		pendingTerminate.value = null
		reload()
	} catch (e) {
		terminateError.value = getErrorMessage(
			e,
			"We couldn't terminate this server.",
		)
	}
}

const pendingResize = ref<VirtualMachineRow | null>(null)
const pendingSnapshot = ref<VirtualMachineRow | null>(null)
const overviewOpensSite = computed(
	() => !!overviewServer.value && !!siteFor(overviewServer.value),
)
// A member can be scoped to some servers, so each dialog follows the server it shows.
const teamActions = computed<ServerActions>(() => ({
	open: canViewServers.value,
	power: canPowerServer.value,
	resize: canResizeServer.value,
	snapshot: canSnapshotServer.value,
	terminate: canTerminateServer.value,
}))
const terminateActions = computed(() =>
	getServerActions(pendingTerminate.value, teamActions.value),
)
const overviewActions = computed(() =>
	getServerActions(overviewServer.value, teamActions.value),
)
const overviewOpen = computed({
	get: () => !!overviewServer.value,
	set: (isOpen: boolean) => {
		if (!isOpen) overviewServer.value = null
	},
})
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
				v-if="
					activeTeam &&
					canCreateServer &&
					!showOnboarding &&
					!(panelOpen && !rows.length)
				"
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
				:allow-open="canViewServers"
				:opening="opening"
				@open="openById"
				@open-server="openBench"
				@open-site="openSite"
				@new-server="goNewServer"
				@cluster-open="onClusterOpen"
			>
				<template #card-actions="{ pin }">
					<ServerRowActions
						v-if="pin.server"
						:server="pin.server"
						:can-open="canViewServers"
						:can-power="canPowerServer"
						:can-resize="canResizeServer"
						:can-terminate="canTerminateServer"
						:can-snapshot="canSnapshotServer"
						:opens-site="!!pin.site"
						side="right"
						:busy="busy === pin.server.resource_id"
						:opening="
							opening === pin.server.resource_id || opening === pin.site?.name
						"
						@overview="overviewServer = $event"
						@open="openServer"
						@start="doStart"
						@stop="doStop"
						@restart="pendingRestart = $event"
						@resize="pendingResize = $event"
						@snapshot="pendingSnapshot = $event"
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
				:can-open="canViewServers"
				:can-power="canPowerServer"
				:can-resize="canResizeServer"
				:can-terminate="canTerminateServer"
				:can-snapshot="canSnapshotServer"
				:can-create="canCreateServer"
				:busy="busy"
				:opening="opening"
				@open-row="openResource"
				@clear-location="locationFilter = null"
				@overview="overviewServer = $event"
				@open="openServer"
				@start="doStart"
				@stop="doStop"
				@restart="pendingRestart = $event"
				@resize="pendingResize = $event"
				@snapshot="pendingSnapshot = $event"
				@terminate="pendingTerminate = $event"
				@create="$router.push('/servers/new')"
			/>

			<!-- Initial load / hard failure / first run — centered over the map -->
			<div
				v-if="loading && !rows.length"
				class="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center"
			>
				<Spinner class="size-5 text-ink-gray-5" />
			</div>
			<div
				v-else-if="error && !rows.length"
				class="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center px-4"
			>
				<Alert
					class="pointer-events-auto w-full max-w-md shadow-lg"
					theme="red"
					title="Couldn't load your servers"
					:description="error"
					:primary-action="{ label: 'Retry', onClick: reloadAll }"
				/>
			</div>
			<!-- First-run onboarding: a dismissible nudge toward the one right action. -->
			<ServerOnboarding
				v-else-if="showOnboarding && !panelOpen"
				@create="$router.push('/servers/new')"
				@dismiss="dismissOnboarding"
			/>
		</div>

		<ConfirmDialog
			v-model:target="pendingRestart"
			title="Restart server"
			confirm-label="Restart"
			:loading="busy === pendingRestart?.resource_id"
			@confirm="confirmRestart"
		>
			<p class="text-p-base text-ink-gray-7">
				Restart
				<span class="font-semibold text-ink-gray-9"
					>{{ pendingRestart?.title || pendingRestart?.resource_id }}</span
				>? It will be unavailable for a moment.
			</p>
		</ConfirmDialog>

		<TerminateServerDialog
			v-model:target="pendingTerminate"
			:loading="busy === pendingTerminate?.resource_id"
			:error="terminateError"
			:can-snapshot="terminateActions.snapshot"
			@confirm="confirmTerminate"
		/>
		<TakeSnapshotDialog v-model:server="pendingSnapshot" />

		<ResizeServerDialog v-model:server="pendingResize" @resized="reloadAll" />
		<ServerOverviewDialog
			v-model:open="overviewOpen"
			:server="overviewServer"
			:can-open="overviewActions.open"
			:can-resize="overviewActions.resize"
			:opens-site="overviewOpensSite"
			:can-snapshot="overviewActions.snapshot"
			@open="openServer"
			@resize="pendingResize = $event"
		/>
		<CreateTeamDialog v-model:open="createTeamOpen" />
	</div>
</template>
