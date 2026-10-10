<script setup lang="ts">
import { Button, TabList, Tabs, TabTrigger } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import AccessTab from '@/components/servers/detail/AccessTab.vue'
import Header from '@/components/servers/detail/Header.vue'
import NetworkingTab from '@/components/servers/detail/NetworkingTab.vue'
import OverviewTab from '@/components/servers/detail/OverviewTab.vue'
import SettingsTab from '@/components/servers/detail/SettingsTab.vue'
import RenameServerDialog from '@/components/servers/RenameServerDialog.vue'
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import TerminateServerDialog from '@/components/servers/TerminateServerDialog.vue'
import SnapshotsPanel from '@/components/snapshots/SnapshotsPanel.vue'
import TakeSnapshotDialog from '@/components/snapshots/TakeSnapshotDialog.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerMapData } from '@/composables/useServerMapData'
import { useServerOverview } from '@/composables/useServerOverview'
import {
	type ServerCommand,
	useServers,
	type VirtualMachineRow,
} from '@/composables/useServers'
import { getServerActions } from '@/lib/capabilities'
import { getErrorMessage } from '@/lib/feedback'
import { METRIC_PERIODS } from '@/lib/serverMetrics'
import type { MetricsRange } from '@/types/servers'

type PowerCommand = Exclude<ServerCommand, 'terminate'>

const TABS = [
	{ label: 'Overview', value: 'overview', iconLeft: 'lucide-gauge' },
	{ label: 'Networking', value: 'networking', iconLeft: 'lucide-network' },
	{ label: 'Access', value: 'access', iconLeft: 'lucide-key-round' },
	{ label: 'Snapshots', value: 'snapshots', iconLeft: 'lucide-camera' },
	{ label: 'Settings', value: 'settings', iconLeft: 'lucide-settings' },
]

const route = useRoute()
const router = useRouter()
const { setBreadcrumbs } = useBreadcrumbs()

const {
	canViewServers,
	canPowerServer,
	canResizeServer,
	canSnapshotServer,
	canTerminateServer,
	canOpenConsole,
} = useCapabilities()

const { servers, sites, loaded, error: fleetError, reload } = useServerMapData()
const { busy, opening, runCommand, openBench, openConsole, openSite } =
	useServers()

const resourceId = computed(() => String(route.params.id))

const server = computed(() =>
	servers.value.find((row) => row.resource_id === resourceId.value),
)

const queryValue = (key: string): string | null =>
	typeof route.query[key] === 'string' ? route.query[key] : null

const metricsRange = computed<MetricsRange>({
	get: () => {
		const period = queryValue('period')

		return {
			period: METRIC_PERIODS.some((option) => option.value === period)
				? String(period)
				: '24h',
			start: queryValue('start'),
			end: queryValue('end'),
		}
	},
	set: ({ period, start, end }) => {
		const isCustom = period === 'custom'

		router.replace({
			query: {
				...route.query,
				period: period === '24h' ? undefined : period,
				start: isCustom ? (start ?? undefined) : undefined,
				end: isCustom ? (end ?? undefined) : undefined,
			},
		})
	},
})

const {
	overview,
	metrics,
	metricsError,
	error: overviewError,
	reload: reloadOverview,
	reloadMetrics,
} = useServerOverview(resourceId, metricsRange)

const details = computed(() =>
	overview.value?.server.resource_id === resourceId.value
		? overview.value
		: null,
)

const site = computed(() =>
	sites.value.find((row) => row.server === server.value?.name),
)

const actions = computed(() =>
	getServerActions(server.value, {
		open: canViewServers.value,
		power: canPowerServer.value,
		resize: canResizeServer.value,
		snapshot: canSnapshotServer.value,
		terminate: canTerminateServer.value,
		console: canOpenConsole.value,
	}),
)

const activeTab = computed({
	get: () => String(route.params.tab || 'overview'),
	set: (tab: string) =>
		router.replace({
			params: { ...route.params, tab: tab === 'overview' ? '' : tab },
			query: tab === 'overview' ? route.query : {},
		}),
})

watch(
	() => server.value?.title,
	(title) =>
		setBreadcrumbs([
			{ label: 'Servers', route: { path: '/servers' } },
			{ label: title || resourceId.value },
		]),
	{ immediate: true },
)

watch(
	() => `${server.value?.status}:${server.value?.pending_action}`,
	(_, previous) => {
		if (previous !== 'undefined:undefined') reloadOverview()
	},
)

const isOpening = computed(
	() =>
		!!server.value &&
		(opening.value === server.value.resource_id ||
			opening.value === site.value?.name),
)

const open = (): void => {
	if (!server.value) return

	if (site.value) {
		openSite(site.value.name)
		return
	}

	openBench(server.value)
}

const pendingCommand = ref<PowerCommand | null>(null)

const commandCopy = computed(() =>
	pendingCommand.value === 'stop'
		? {
				title: 'Stop server',
				label: 'Stop',
				message: 'Its sites go offline until you start it again.',
			}
		: {
				title: 'Restart server',
				label: 'Restart',
				message: 'Its sites are unavailable for a moment while it restarts.',
			},
)

const command = async (name: PowerCommand): Promise<void> => {
	if (!server.value) return

	if (name !== 'start' && pendingCommand.value !== name) {
		pendingCommand.value = name
		return
	}

	if (await runCommand(name, server.value)) reload()

	pendingCommand.value = null
}

const resizing = ref(false)
const renaming = ref(false)
const pendingSnapshot = ref<VirtualMachineRow | null>(null)

const pendingTerminate = ref<VirtualMachineRow | null>(null)
const terminateError = ref('')

const terminate = async (
	target: VirtualMachineRow,
	takeSnapshot: boolean,
): Promise<void> => {
	terminateError.value = ''

	try {
		await runCommand('terminate', target, { takeSnapshot, throwOnError: true })
		pendingTerminate.value = null
		router.push('/servers')
	} catch (failure) {
		terminateError.value = getErrorMessage(
			failure,
			"We couldn't terminate this server.",
		)
	}
}
</script>

<template>
	<div class="h-full overflow-y-auto">
		<div class="mx-auto w-full max-w-5xl p-3 md:p-4 xl:pt-8">
			<div v-if="!loaded && !fleetError" class="space-y-6" aria-busy="true">
				<div class="h-24 animate-pulse rounded-6 bg-surface-gray-2" />
				<div
					class="h-7 w-96 max-w-full animate-pulse rounded-4 bg-surface-gray-2"
				/>
			</div>

			<EmptyState
				v-else-if="!server && fleetError"
				icon="lucide-cloud-off"
				title="Server couldn't load"
				:description="fleetError"
			>
				<template #action>
					<Button label="Retry" @click="reload" />
				</template>
			</EmptyState>

			<EmptyState
				v-else-if="!server"
				icon="lucide-server-off"
				title="Server not found"
				description="It may have been terminated, or it belongs to another team."
			>
				<template #action>
					<Button label="Back to servers" route="/servers" />
				</template>
			</EmptyState>

			<template v-else>
				<Header
					:server="server"
					:details="details?.server ?? null"
					:actions="actions"
					:site-url="site?.url ?? null"
					:opening="isOpening"
					:busy="busy === server.resource_id"
					@open="open"
					@pilot="openBench(server)"
					@command="command"
					@console="openConsole(server)"
					@rename="renaming = true"
					@snapshot="pendingSnapshot = server"
					@resize="resizing = true"
					@terminate="pendingTerminate = server"
				/>

				<Tabs v-model="activeTab" class="mt-4">
					<TabList variant="browser-tab" size="md">
						<TabTrigger
							v-for="tab in TABS"
							:key="tab.value"
							:value="tab.value"
							:label="tab.label"
							:icon-left="tab.iconLeft"
						/>
					</TabList>
				</Tabs>
				<SnapshotsPanel
					v-if="activeTab === 'snapshots'"
					:server="server"
					class="mt-6"
				/>

				<SettingsTab
					v-else-if="activeTab === 'settings'"
					:server="server"
					:actions="actions"
					class="mt-6"
					@resize="resizing = true"
					@terminate="pendingTerminate = server"
				/>

				<EmptyState
					v-else-if="!details && overviewError"
					icon="lucide-cloud-off"
					title="Details couldn't load"
					:description="overviewError"
					class="mt-6"
				>
					<template #action>
						<Button label="Retry" @click="reloadOverview" />
					</template>
				</EmptyState>

				<div v-else-if="!details" class="mt-6 space-y-4" aria-busy="true">
					<div class="h-5 w-24 animate-pulse rounded-4 bg-surface-gray-2" />
					<div class="grid gap-3 md:grid-cols-3 md:gap-4">
						<div
							v-for="index in 3"
							:key="index"
							class="h-32 animate-pulse rounded-6 bg-surface-gray-1"
						/>
					</div>
				</div>

				<OverviewTab
					v-else-if="activeTab === 'overview'"
					v-model:range="metricsRange"
					:overview="details"
					:metrics="metrics"
					:metrics-error="metricsError"
					@refresh="reloadMetrics"
					class="mt-6"
				/>

				<NetworkingTab
					v-else-if="activeTab === 'networking'"
					:server="server"
					:overview="details"
					class="mt-6"
				/>

				<AccessTab v-else :overview="details" class="mt-6" />
			</template>
		</div>

		<ConfirmDialog
			v-model:target="pendingCommand"
			:title="commandCopy.title"
			:confirm-label="commandCopy.label"
			:loading="busy === server?.resource_id"
			@confirm="command"
		>
			<p class="text-p-base text-ink-gray-7">{{ commandCopy.message }}</p>
		</ConfirmDialog>

		<TerminateServerDialog
			v-model:target="pendingTerminate"
			:loading="busy === pendingTerminate?.resource_id"
			:error="terminateError"
			:can-snapshot="actions.snapshot"
			@confirm="terminate"
		/>

		<TakeSnapshotDialog v-model:server="pendingSnapshot" />

		<RenameServerDialog
			v-if="server"
			v-model:open="renaming"
			:server="server"
			@renamed="reload"
		/>

		<ResizeServerDialog
			v-model:open="resizing"
			:server="server ?? null"
			@resized="reload"
		/>
	</div>
</template>

<style scoped>
/* temporary for now  until i add this inf rappeui*/
:deep([data-slot="tab-list"][data-variant="browser-tab"]) {
	@apply border-b-outline-gray-2;
}

:deep([data-variant="browser-tab"] [data-slot="tab-indicator"]) {
	@apply border-x-outline-gray-2 border-t-outline-gray-2;
}
</style>
