<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { computed, ref } from 'vue'

import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'

import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import StatusRing from '@/components/servers/StatusRing.vue'

import type { ConsoleMode, VirtualMachineRow } from '@/composables/useServers'
import { type ResourceRow, STATUS_FILTERS } from '@/lib/serverMap'

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

const query = ref(createListViewQuery({ pageSize: 20 }))

const columns: ListViewColumn<ResourceRow>[] = [
	{
		key: 'name',
		label: 'Name',
		value: (row) => `${row.name} ${row.provider ?? ''}`,
		width: 'minmax(0,2fr)',
		sortable: true,
	},
	{
		key: 'region',
		label: 'Region',
		value: (row) => row.regionLabel,
		width: 'minmax(0,1fr)',
		sortable: true,
		class: 'max-md:hidden',
	},
	{
		key: 'status',
		label: 'Status',
		value: (row) => row.visual.label,
		width: '8rem',
		sortable: true,
	},
	{ key: 'actions', label: '', width: '2.5rem', align: 'end' },
]

const regionOptions = computed(() =>
	[...new Set(props.rows.map((row) => row.regionLabel))]
		.sort()
		.map((label) => ({ label, value: label })),
)

const filters = computed<ListViewFilter[]>(() => [
	{
		key: 'status',
		label: 'Status',
		allLabel: 'All statuses',
		options: STATUS_FILTERS.map((status) => ({
			label: status.label,
			value: status.label,
			dot: status.dot,
		})),
	},
	{
		key: 'region',
		label: 'Region',
		allLabel: 'All regions',
		options: regionOptions.value,
	},
])
</script>

<template>
	<ListView
		v-model:query="query"
		:rows="rows"
		:columns="columns"
		:row-key="(row) => row.id"
		:filters="filters"
		searchable
		search-placeholder="Search by name, region or provider"
		item-label="server"
		row-class="min-h-14 py-1.5"
		:empty-state="{
			title: 'No servers match',
			description: 'Try a different search or clear the filters.',
		}"
		@row-click="$emit('openRow', $event)"
	>
		<template #name="{ row }">
			<span class="flex min-w-0 items-center gap-3">
				<span class="relative shrink-0">
					<StatusRing
						class="-inset-0.5"
						:motion="row.visual.motion"
						:color="row.visual.dot"
						:is-settled="settledIds.has(row.id)"
					/>
					<ProviderAvatar
						class="relative"
						:provider="row.provider"
						:size="32"
					/>
				</span>

				<span class="min-w-0">
					<span class="block truncate text-sm-medium text-ink-gray-9">
						{{ row.name }}
					</span>
					<span class="mt-0.5 block truncate text-sm text-ink-gray-5">
						{{ row.specs || row.regionLabel }}
					</span>
				</span>
			</span>
		</template>

		<template #region="{ row }">
			<span class="truncate text-sm text-ink-gray-6">
				{{ row.flag }}
				{{ row.regionLabel }}
			</span>
		</template>

		<template #status="{ row }">
			<Badge
				:label="row.visual.label"
				:theme="row.visual.badgeTheme"
				size="sm"
			/>
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
