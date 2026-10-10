<script setup lang="ts">
import { Alert, Button, Spinner, TabButtons } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import MapHealthStrips from '@/components/servers/MapHealthStrips.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import ServerFilters from '@/components/servers/ServerFilters.vue'
import ServerListPanel from '@/components/servers/ServerListPanel.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import TerminateServerDialog from '@/components/servers/TerminateServerDialog.vue'
import TakeSnapshotDialog from '@/components/snapshots/TakeSnapshotDialog.vue'
import { useFleetCommands } from '@/composables/useFleetCommands'
import { useServerFleet } from '@/composables/useServerFleet'
import { useServerLink } from '@/composables/useServerLink'
import { useServerNavigation } from '@/composables/useServerNavigation'
import { useServers } from '@/composables/useServers'
import { getServerActions, type ServerActions } from '@/lib/capabilities'
import { infoToast } from '@/lib/feedback'
import { canChange } from '@/lib/status'

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
	canOpenConsole,
	canViewServers,
	canCreateServer,
	activeTeam,
	rows,
	query: q,
	statusFilter,
	regionSelection,
	locationFilter,
	statusOptions,
	regionOptions,
	panelRows,
	listTitle,
	pins,
	spots,
	frame,
	mapView,
	hasMapViewChoice,
	settledIds,
	servers,
} = useServerFleet()

const MAP_VIEW_OPTIONS = [
	{ label: 'My regions', value: 'fleet' },
	{ label: 'World', value: 'world' },
]
const { refreshing, stale, busy, opening, openConsole } = useServers()

// With no servers yet the map names each region, so the empty map invites a choice.
const isFleetEmpty = computed(() => !loading.value && !rows.value.length)

const hoverId = ref<string | null>(null)
const { showServer, openServer, openResource, openById, openBench, openSite } =
	useServerNavigation(rows, sites)

// — Wiring. Pin / cluster-row clicks go straight to the live site or server.
//   A cluster click narrows the list to that spot.
function onClusterOpen(payload: { ids: string[]; label: string }): void {
	locationFilter.value = payload
}
function goNewServer(region: string): void {
	router.push({ path: '/servers/new', query: { region } })
}

// Opening the map shows the current fleet. The feed is a shared singleton that only
// reloads on team-ready or a live event, so a server created while this page was
// unmounted (the New server flow) wouldn't be here yet — reload on every entry.
onMounted(() => {
	if (activeTeam.value) reload()
	if (typeof route.query.site === 'string') q.value = route.query.site
})

const {
	refresh,
	start,
	stop,
	pendingRestart,
	confirmRestart,
	pendingResize,
	isResizeOpen,
	openResize,
	pendingSnapshot,
	pendingTerminate,
	terminateError,
	confirmTerminate,
} = useFleetCommands(reload)

// A member can be scoped to some servers, so each dialog follows the server it shows.
const teamActions = computed<ServerActions>(() => ({
	open: canViewServers.value,
	power: canPowerServer.value,
	resize: canResizeServer.value,
	snapshot: canSnapshotServer.value,
	terminate: canTerminateServer.value,
	console: canOpenConsole.value,
}))
const terminateActions = computed(() =>
	getServerActions(pendingTerminate.value, teamActions.value),
)

// A link from a server's own dashboard opens that server here.
useServerLink(
	{ activeTeam, servers, reload },
	{
		overview: showServer,
		resize: (server) => {
			if (!canChange(server))
				infoToast("This server can't be resized right now.")
			else if (!getServerActions(server, teamActions.value).resize)
				infoToast("You can't resize this server.")
			else openResize(server)
		},
	},
)
</script>

<template>
	<div class="flex h-full flex-col">
		<Teleport defer to="#header-actions">
			<Button
				v-if="activeTeam"
				label="Refresh"
				icon-left="lucide-refresh-cw"
				:loading="refreshing"
				@click="refresh"
			/>
			<!-- An empty fleet's list carries the one New-server button instead. -->
			<Button
				v-if="activeTeam && canCreateServer && !isFleetEmpty"
				variant="solid"
				label="New server"
				icon-left="lucide-plus"
				@click="$router.push('/servers/new')"
			/>
		</Teleport>

		<!-- The list stays in view on the right. Below lg, it stacks over a short map. -->
		<div class="flex min-h-0 flex-1 flex-col lg:flex-row-reverse">
			<ServerListPanel
				class="vt-server-list min-h-0 flex-1 overflow-hidden border-b border-outline-gray-1 lg:w-96 lg:flex-none lg:border-b-0 lg:border-l"
				v-model:query="q"
				v-model:hover-id="hoverId"
				:title="listTitle"
				:rows="panelRows"
				:has-rows="rows.length > 0"
				:location-filter="locationFilter"
				:settled-ids="settledIds"
				:can-open="canViewServers"
				:can-power="canPowerServer"
				:can-resize="canResizeServer"
				:can-terminate="canTerminateServer"
				:can-snapshot="canSnapshotServer"
				:can-open-console="canOpenConsole"
				:can-create="canCreateServer"
				:busy="busy"
				:opening="opening"
				@open-row="openResource"
				@clear-location="locationFilter = null"
				@overview="showServer"
				@open="openServer"
				@pilot="openBench"
				@start="start"
				@stop="stop"
				@restart="pendingRestart = $event"
				@resize="openResize"
				@snapshot="pendingSnapshot = $event"
				@console="openConsole"
				@terminate="pendingTerminate = $event"
				@create="$router.push('/servers/new')"
			/>

			<!-- The map card, inset beside the list. Filters and alerts float above it;
			     `isolate` keeps their z-indexes from leaking above body-portaled menus. -->
			<div
				class="vt-server-map relative isolate m-2 h-72 shrink-0 overflow-hidden rounded-6 border border-outline-gray-1 lg:h-auto lg:flex-1"
			>
				<ServerMap
					class="absolute inset-0"
					:pins="pins"
					:spots="spots"
					:frame="frame"
					:settled-ids="settledIds"
					:label-spots="isFleetEmpty"
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
							:can-open-console="canOpenConsole"
							:opens-site="!!pin.site"
							:busy="busy === pin.server.resource_id"
							:opening="
								opening === pin.server.resource_id ||
								opening === pin.site?.name
							"
							@overview="showServer"
							@open="openServer"
							@pilot="openBench"
							@start="start"
							@stop="stop"
							@restart="pendingRestart = $event"
							@resize="openResize"
							@snapshot="pendingSnapshot = $event"
							@console="openConsole"
							@terminate="pendingTerminate = $event"
						/>
					</template>
				</ServerMap>

				<MapHealthStrips
					:stale="stale"
					:error="error"
					:has-rows="rows.length > 0"
					@retry="reload"
				/>

				<ServerFilters
					v-model:status-filter="statusFilter"
					v-model:region-selection="regionSelection"
					:status-options="statusOptions"
					:region-options="regionOptions"
				/>

				<!-- Names what the map frames, so a fleet in one region is a choice, not a hidden crop. -->
				<div
					v-if="hasMapViewChoice"
					class="absolute bottom-2 right-2 rounded-5 border border-outline-gray-2 bg-surface-base"
				>
					<TabButtons
						v-model="mapView"
						variant="ghost"
						aria-label="Map view"
						:options="MAP_VIEW_OPTIONS"
					/>
				</div>

				<!-- Initial load / hard failure — centered over the map -->
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
						:primary-action="{ label: 'Retry', onClick: reload }"
					/>
				</div>
			</div>
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

		<ResizeServerDialog
			v-model:open="isResizeOpen"
			:server="pendingResize"
			@resized="reload"
		/>
	</div>
</template>
