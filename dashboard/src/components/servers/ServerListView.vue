<script setup lang="ts">
import { TabButtons, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'

import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'

import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import StatusRing from '@/components/servers/StatusRing.vue'

import type { ConsoleMode, VirtualMachineRow } from '@/composables/useServers'
import { timeAgo } from '@/lib/datetime'
import type { ResourceRow, ServerVisual } from '@/lib/serverMap'
import { formatMemory } from '@/lib/units'

interface ServerListViewProps {
	rows: ResourceRow[]
	settledIds: Set<string>
	canOpen: boolean
	canPower: boolean
	canResize: boolean
	canTerminate: boolean
	canSnapshot?: boolean
	canOpenConsole?: boolean
	busy: string | null
	opening: string | null
}

const props = defineProps<ServerListViewProps>()

defineEmits<{
	openRow: [row: ResourceRow]
	overview: [server: VirtualMachineRow]
	open: [server: VirtualMachineRow]
	pilot: [server: VirtualMachineRow]
	start: [server: VirtualMachineRow]
	stop: [server: VirtualMachineRow]
	restart: [server: VirtualMachineRow]
	resize: [server: VirtualMachineRow]
	snapshot: [server: VirtualMachineRow]
	console: [server: VirtualMachineRow, mode: ConsoleMode]
	terminate: [server: VirtualMachineRow]
}>()

const IMAGE_ICONS: Record<string, string> = {
	pilot: 'lucide-box',
	ubuntu: 'lucide-terminal',
	apps: 'lucide-package',
}

const imageIcon = (row: ResourceRow) =>
	IMAGE_ICONS[row.server?.image_offering ?? ''] ?? 'lucide-server'

type StatusTab = 'all' | 'running' | 'progress' | 'attention'

const STATUS_TABS: Record<StatusTab, ServerVisual['key'][] | null> = {
	all: null,
	running: ['active'],
	progress: ['settingUp', 'resizing', 'terminating'],
	attention: ['broken', 'paused', 'stopped'],
}

const query = ref(createListViewQuery({ pageSize: 20 }))
const statusTab = ref<StatusTab>('all')

const isInTab = (row: ResourceRow, tab: StatusTab) =>
	STATUS_TABS[tab]?.includes(row.visual.key) ?? true

const tabRows = computed(() =>
	props.rows.filter((row) => isInTab(row, statusTab.value)),
)

const STATUS_TAB_OPTIONS = [
	{ label: 'All', value: 'all' },
	{ label: 'Running', value: 'running' },
	{ label: 'In progress', value: 'progress' },
	{ label: 'Attention', value: 'attention' },
]

const planOf = (row: ResourceRow) =>
	row.server?.plan_title || row.server?.plan || ''

const specsOf = (server?: VirtualMachineRow) =>
	[
		server?.vcpus && `${server.vcpus} vCPU`,
		server?.memory_megabytes && formatMemory(server.memory_megabytes),
		server?.disk_gigabytes && `${server.disk_gigabytes} GB`,
	]
		.filter(Boolean)
		.join(' · ')

const columns: ListViewColumn<ResourceRow>[] = [
	{
		key: 'name',
		label: 'Server',
		value: (row) => `${row.name} ${row.server?.image_title ?? ''}`,
		width: 'minmax(12rem,1fr)',
		sortable: true,
	},
	{
		key: 'status',
		label: 'Status',
		value: (row) => row.visual.label,
		width: 'minmax(8rem,1fr)',
		sortable: true,
	},
	{
		key: 'region',
		label: 'Region',
		value: (row) => `${row.regionLabel} ${row.server?.public_ipv4 ?? ''}`,
		width: 'minmax(11rem,1fr)',
		sortable: true,
	},
	{
		key: 'plan',
		label: 'Plan',
		value: planOf,
		width: 'minmax(10rem,1fr)',
		sortable: true,
	},
	{
		key: 'version',
		label: 'Version',
		value: (row) => row.server?.frappe_version ?? '',
		width: 'minmax(6rem,1fr)',
		sortable: true,
	},
	{ key: 'actions', label: '', width: '2.5rem', align: 'end' },
]

const optionsFor = (read: (row: ResourceRow) => string | undefined) =>
	[...new Set(props.rows.map(read).filter(Boolean) as string[])]
		.sort()
		.map((value) => ({ label: value, value }))

const filters = computed<ListViewFilter[]>(() => [
	{
		key: 'region',
		label: 'Region',
		allLabel: 'All regions',
		options: optionsFor((row) => row.regionLabel),
	},
	{
		key: 'plan',
		label: 'Plan',
		allLabel: 'All plans',
		options: optionsFor(planOf),
	},
	{
		key: 'version',
		label: 'Version',
		allLabel: 'All versions',
		options: optionsFor((row) => row.server?.frappe_version),
	},
])
</script>

<template>
	<ListView
		v-model:query="query"
		min-width="56rem"
		:rows="tabRows"
		:columns="columns"
		:row-key="(row) => row.id"
		:filters="filters"
		searchable
		search-placeholder="Search by name, region or IP"
		item-label="server"
		row-class="min-h-14 py-1.5"
		:empty-state="{
			title: 'No servers match',
			description: 'Try a different search or clear the filters.',
		}"
		@row-click="$emit('openRow', $event)"
	>
		<template #filters>
			<TabButtons
				class="ml-auto"
				v-model="statusTab"
				:options="STATUS_TAB_OPTIONS"
			/>
		</template>

		<template #name="{ row }">
			<span class="flex min-w-0 items-center gap-3">
				<span class="relative shrink-0">
					<StatusRing
						class="-inset-0.5"
						:motion="row.visual.motion"
						:color="row.visual.dot"
						:is-settled="settledIds.has(row.id)"
					/>
					<Tooltip :text="row.server?.image_description ?? ''">
						<span
							class="relative grid size-8 place-items-center rounded-4 bg-surface-gray-1 text-ink-gray-5"
						>
							<span class="size-4" :class="imageIcon(row)" />
						</span>
					</Tooltip>
				</span>

				<span class="flex min-w-0 flex-col gap-0.5">
					<span class="truncate text-sm-medium text-ink-gray-9">
						{{ row.name }}
					</span>
					<span class="truncate text-xs text-ink-gray-5">
						{{ row.server?.image_title }}
					</span>
				</span>
			</span>
		</template>

		<template #status="{ row }">
			<span class="flex min-w-0 flex-col gap-0.5">
				<span class="flex items-center gap-2 text-sm text-ink-gray-7">
					<span
						class="size-2 shrink-0 rounded-full"
						:style="{ background: row.visual.dot }"
					/>
					{{ row.visual.label }}
				</span>
				<span class="truncate text-xs tabular-nums text-ink-gray-5">
					{{ timeAgo(row.server?.state_observed_at) || '-' }}
				</span>
			</span>
		</template>

		<template #region="{ row }">
			<span class="flex min-w-0 flex-col gap-0.5">
				<span class="truncate text-sm text-ink-gray-7">
					{{ row.flag }}
					{{ row.regionLabel }}
				</span>
				<span class="flex min-w-0 items-center gap-1 text-xs text-ink-gray-5">
					<template v-if="row.server?.public_ipv4">
						<span class="truncate tabular-nums">
							{{ row.server.public_ipv4 }}
						</span>
						<CopyButton class="relative" :text="row.server.public_ipv4" />
					</template>
					<span v-else class="truncate">No public IP</span>

					<Tooltip
						v-if="row.server"
						text="Your team's WireGuard VPN devices reach this server at its private address."
						:disabled="!row.server.has_wireguard_access"
					>
						<span class="relative shrink-0">
							· VPN {{ row.server.has_wireguard_access ? 'on' : 'off' }}
						</span>
					</Tooltip>
				</span>
			</span>
		</template>

		<template #plan="{ row }">
			<span class="flex min-w-0 flex-col gap-0.5">
				<span
					:class="[
						'truncate text-sm',
						planOf(row) ? 'text-ink-gray-7' : 'text-ink-gray-4',
					]"
				>
					{{ planOf(row) || '-' }}
				</span>
				<span class="truncate text-xs tabular-nums text-ink-gray-5">
					{{ specsOf(row.server) }}
				</span>
			</span>
		</template>

		<template #version="{ row }">
			<span
				:class="[
					'truncate text-sm',
					row.server?.frappe_version ? 'text-ink-gray-7' : 'text-ink-gray-4',
				]"
			>
				{{ row.server?.frappe_version || '-' }}
			</span>
		</template>

		<template #actions="{ row }">
			<ServerRowActions
				v-if="row.server"
				:server="row.server"
				:can-open="canOpen"
				:can-power="canPower"
				:can-resize="canResize"
				:can-terminate="canTerminate"
				:can-snapshot="canSnapshot"
				:can-open-console="canOpenConsole"
				:site="row.site?.name"
				:busy="busy === row.server.resource_id"
				:opening="
					opening === row.server.resource_id || opening === row.site?.name
				"
				@overview="$emit('overview', $event)"
				@open="$emit('open', $event)"
				@pilot="$emit('pilot', $event)"
				@start="$emit('start', $event)"
				@stop="$emit('stop', $event)"
				@restart="$emit('restart', $event)"
				@resize="$emit('resize', $event)"
				@snapshot="$emit('snapshot', $event)"
				@console="(server, mode) => $emit('console', server, mode)"
				@terminate="$emit('terminate', $event)"
			/>
		</template>
	</ListView>
</template>
