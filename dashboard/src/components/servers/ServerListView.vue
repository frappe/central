<script setup lang="ts">
import { TabButtons, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import ImageIcon from '@/components/servers/ImageIcon.vue'
import ServerAddress from '@/components/servers/ServerAddress.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import { useAuth } from '@/composables/useAuth'
import type { ConsoleMode, VirtualMachineRow } from '@/composables/useServers'
import { formatCalendarDate } from '@/lib/datetime'
import { imageLabel, type ResourceRow } from '@/lib/serverMap'
import { __ } from '@/lib/translate'
import { formatMemory, gigabytesToMegabytes } from '@/lib/units'

interface ServerListViewProps {
	rows: ResourceRow[]
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

const { currentUser } = useAuth()

type StatusTab = 'all' | 'running' | 'stopped' | 'attention'

const STATUS_TABS: Record<StatusTab, (row: ResourceRow) => boolean> = {
	all: () => true,
	running: (row) => row.visual.key === 'active',
	stopped: (row) => row.visual.key === 'stopped',
	attention: (row) => ['broken', 'paused'].includes(row.visual.key),
}

const query = ref(
	createListViewQuery({
		pageSize: 20,
		sort: { key: 'created', direction: 'desc' },
	}),
)
const statusTab = ref<StatusTab>('all')

const tabRows = computed(() => props.rows.filter(STATUS_TABS[statusTab.value]))

const countIn = (tab: StatusTab) => props.rows.filter(STATUS_TABS[tab]).length

const statusTabOptions = computed(() => [
	{ label: __('All {0}', [countIn('all')]), value: 'all' },
	{ label: __('Running {0}', [countIn('running')]), value: 'running' },
	{ label: __('Stopped {0}', [countIn('stopped')]), value: 'stopped' },
	{
		label: __('Needs attention {0}', [countIn('attention')]),
		value: 'attention',
	},
])

// Most teams run in one region, where a region column and filter would say nothing.
const regionLabels = computed(() => [
	...new Set(props.rows.map((row) => row.regionLabel).filter(Boolean)),
])
const isMultiRegion = computed(() => regionLabels.value.length > 1)

const isRunningAction = (row: ResourceRow) => row.visual.motion === 'progress'

const creatorLabel = (server?: VirtualMachineRow) =>
	server?.created_by === currentUser.value
		? __('You')
		: server?.created_by_name || server?.created_by || ''

const creatorFirstName = (server?: VirtualMachineRow) =>
	creatorLabel(server).split(' ')[0]

const sizeOf = (server?: VirtualMachineRow) =>
	[
		server?.vcpus && `${server.vcpus} vCPU`,
		server?.memory_megabytes && formatMemory(server.memory_megabytes),
	]
		.filter(Boolean)
		.join(' · ')

const diskOf = (server?: VirtualMachineRow) =>
	server?.disk_gigabytes
		? __('{0} disk', [
				formatMemory(gigabytesToMegabytes(server.disk_gigabytes)),
			])
		: ''

const compareBy =
	(read: (server?: VirtualMachineRow) => string | number | null | undefined) =>
	(left: ResourceRow, right: ResourceRow) =>
		String(read(left.server) ?? '').localeCompare(
			String(read(right.server) ?? ''),
			undefined,
			{ numeric: true },
		)

const columns = computed<ListViewColumn<ResourceRow>[]>(() => [
	{
		key: 'name',
		label: __('Server'),
		value: (row) => `${row.name} ${imageLabel(row.server)}`,
		width: 'minmax(14rem,1.6fr)',
		sortable: true,
		compare: (left, right) => left.name.localeCompare(right.name),
	},
	{
		key: 'status',
		label: __('Status'),
		value: (row) => row.visual.label,
		width: 'minmax(9rem,1fr)',
		sortable: true,
	},
	{
		key: 'address',
		label: __('Address'),
		value: (row) => `${row.site?.url ?? ''} ${row.server?.public_ipv4 ?? ''}`,
		width: 'minmax(12rem,1.3fr)',
	},
	{
		key: 'size',
		label: __('Size'),
		value: (row) => sizeOf(row.server),
		width: 'minmax(8rem,0.8fr)',
		sortable: true,
		compare: compareBy(
			(server) => (server?.vcpus ?? 0) * 1e6 + (server?.memory_megabytes ?? 0),
		),
	},
	...(isMultiRegion.value
		? [
				{
					key: 'region',
					label: __('Region'),
					value: (row: ResourceRow) => row.regionLabel,
					width: 'minmax(7rem,0.8fr)',
					sortable: true,
				},
			]
		: []),
	{
		key: 'created',
		label: __('Created'),
		value: (row) =>
			`${creatorLabel(row.server)} ${row.server?.created_by_email ?? ''} ${formatCalendarDate(row.server?.creation)}`,
		width: 'minmax(9rem,0.9fr)',
		sortable: true,
		compare: compareBy((server) => server?.creation),
	},
	{ key: 'actions', label: '', width: '2.5rem', align: 'end' },
])

const optionsFrom = (
	pairs: [value: string | null | undefined, label: string | null | undefined][],
) =>
	[...new Map(pairs.filter(([value]) => value) as [string, string][]).entries()]
		.map(([value, label]) => ({ label: label || value, value }))
		.sort((left, right) => left.label.localeCompare(right.label))

// The signed-in user leads the creator filter, as "You".
const creatorOptions = computed(() => {
	const options = optionsFrom(
		props.rows.map((row) => [row.server?.created_by, creatorLabel(row.server)]),
	)
	const isYou = (option: { value: string }) =>
		option.value === currentUser.value
	return [
		...options.filter(isYou),
		...options.filter((option) => !isYou(option)),
	]
})

const filters = computed<ListViewFilter[]>(() => [
	{
		key: 'created',
		label: __('Created by'),
		allLabel: __('Anyone'),
		options: creatorOptions.value,
	},
	{
		key: 'name',
		label: __('Image'),
		allLabel: __('All images'),
		options: optionsFrom(
			props.rows.map((row) => [imageLabel(row.server), imageLabel(row.server)]),
		),
	},
	...(isMultiRegion.value
		? [
				{
					key: 'region',
					label: __('Region'),
					allLabel: __('All regions'),
					options: regionLabels.value.map((label) => ({ label, value: label })),
				},
			]
		: []),
])
</script>

<template>
	<ListView
		v-model:query="query"
		min-width="60rem"
		:rows="tabRows"
		:columns="columns"
		:row-key="(row) => row.id"
		:filters="filters"
		searchable
		:search-placeholder="__('Search by name, domain or IP')"
		:show-count="false"
		row-class="min-h-11"
		:empty-state="{
			title: __('No servers match'),
			description: __('Try a different search or clear the filters.'),
		}"
		:external-filter-active="statusTab !== 'all'"
		@row-click="$emit('openRow', $event)"
		@clear-filters="statusTab = 'all'"
	>
		<template #filters>
			<TabButtons
				class="ml-auto"
				v-model="statusTab"
				:options="statusTabOptions"
			/>
		</template>

		<template #name="{ row }">
			<span class="flex min-w-0 items-center gap-3">
				<Tooltip :text="imageLabel(row.server)">
					<span
						class="relative grid size-8 shrink-0 place-items-center rounded-4 bg-surface-gray-2 text-ink-gray-5 dark:bg-surface-gray-1"
					>
						<ImageIcon class="size-4" :offering="row.server?.image_offering" />
					</span>
				</Tooltip>
				<span class="truncate text-base-medium text-ink-gray-9">
					{{ row.name }}
				</span>
			</span>
		</template>

		<template #status="{ row }">
			<span class="flex min-w-0 items-center gap-2 text-base text-ink-gray-7">
				<span class="relative flex size-2 shrink-0">
					<span
						v-if="isRunningAction(row)"
						class="absolute inset-0 animate-ping rounded-full opacity-60"
						:style="{ background: row.visual.dot }"
					/>
					<span
						class="relative size-2 rounded-full"
						:style="{ background: row.visual.dot }"
					/>
				</span>
				<span class="truncate">{{ row.visual.label }}</span>
			</span>
		</template>

		<template #address="{ row }">
			<ServerAddress :row="row" />
		</template>

		<template #size="{ row }">
			<Tooltip :text="diskOf(row.server)">
				<span class="relative truncate text-sm tabular-nums text-ink-gray-7">
					{{ sizeOf(row.server) || '-' }}
				</span>
			</Tooltip>
		</template>

		<template #region="{ row }">
			<span class="truncate text-base text-ink-gray-7">
				{{ row.regionLabel }}
			</span>
		</template>

		<template #created="{ row }">
			<Tooltip :text="creatorLabel(row.server)">
				<span
					class="relative flex min-w-0 items-baseline gap-1.5 text-sm tabular-nums"
				>
					<span class="shrink-0 text-ink-gray-7">
						{{ formatCalendarDate(row.server?.creation) }}
					</span>
					<span
						v-if="creatorLabel(row.server)"
						class="truncate text-ink-gray-4"
					>
						{{ __('by {0}', [creatorFirstName(row.server)]) }}
					</span>
				</span>
			</Tooltip>
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
