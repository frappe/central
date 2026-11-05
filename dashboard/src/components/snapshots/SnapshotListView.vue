<script setup lang="ts">
import { Badge, Button, Dialog, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import { ACCESS_LOCKED_REASON } from '@/lib/capabilities'
import { formatDate, money } from '@/lib/format'
import {
	SNAPSHOT_STATUS_THEME,
	SNAPSHOT_TYPE_LABEL,
	snapshotCostLabel,
} from '@/lib/snapshots'
import type { VMSnapshotRow } from '@/types/snapshots'

interface SnapshotListViewProps {
	snapshots: VMSnapshotRow[]
	loading: boolean
	error: string
	currency: string
	/** The viewer holds server:snapshot on some server. Each row still checks its own. */
	canManage: boolean
	/** The viewer can create a server, which restoring a snapshot does. */
	canRestore: boolean
	/** How many of each server's newest snapshots are free. */
	freePerServer: number
	/** Search to open with, such as the server a link came from. */
	initialSearch?: string
	serverScoped?: boolean
	/** The server runs a free trial, which takes no snapshots until it converts. */
	isAccessLocked?: boolean
}

// Presentational: emits what the customer chose; the page owns the dialogs and calls.
const props = defineProps<SnapshotListViewProps>()
const emit = defineEmits<{
	retry: []
	take: []
	keep: [snapshot: VMSnapshotRow]
	restore: [snapshot: VMSnapshotRow]
	delete: [snapshots: VMSnapshotRow[]]
}>()

const query = ref(
	createListViewQuery({ pageSize: 20, search: props.initialSearch ?? '' }),
)

const pricingRule = computed(() =>
	props.freePerServer
		? `The newest ${props.freePerServer} snapshots per server are free. Older snapshots are billed by size.`
		: 'Each snapshot is billed by size until you delete it.',
)
const errorSnapshot = ref<VMSnapshotRow | null>(null)
const errorOpen = computed({
	get: () => errorSnapshot.value !== null,
	set: (open: boolean) => {
		if (!open) errorSnapshot.value = null
	},
})
// Count every snapshot outside the free allowance, even before its billing record opens.
const monthlyTotal = computed(() => {
	const billed = props.snapshots.filter(
		(row) => row.status === 'Available' && !row.is_free,
	)
	if (billed.some((row) => row.monthly_cost == null)) return 'Price not set'

	const total = billed.reduce((sum, row) => sum + (row.monthly_cost ?? 0), 0)
	return `${money(total, props.currency, { trimTrailingZeros: true })} / month`
})

const searchPlaceholder = computed(() =>
	props.serverScoped ? 'Search snapshots' : 'Search by snapshot or server name',
)

const SERVER_SCOPED_HIDDEN = ['type', 'cost']

const columns = computed<ListViewColumn<VMSnapshotRow>[]>(() =>
	allColumns.value.filter(
		(column) =>
			!props.serverScoped || !SERVER_SCOPED_HIDDEN.includes(column.key),
	),
)

const allColumns = computed<ListViewColumn<VMSnapshotRow>[]>(() => [
	{
		key: 'snapshot',
		label: 'Snapshot',
		value: (row) => `${row.title} ${row.server_title}`,
		sortable: true,
	},
	{
		key: 'type',
		label: 'Type',
		value: (row) => row.snapshot_type,
		width: '6rem',
		sortable: true,
	},
	{
		key: 'size',
		label: 'Size',
		value: (row) => row.size_mib,
		width: '5.5rem',
		sortable: true,
	},
	{
		key: 'created',
		label: 'Created',
		value: (row) => row.creation,
		width: '7.5rem',
		sortable: true,
		class: 'max-md:hidden',
	},
	{
		key: 'cost',
		label: 'Cost',
		value: (row) => snapshotCostLabel(row, props.currency),
		width: '10rem',
	},
	{ key: 'status', label: 'Status', width: '7rem', sortable: true },
	{ key: 'actions', label: '', width: '2.5rem', align: 'end' },
])

const visibleFilters = computed(() =>
	props.serverScoped
		? filters.filter((filter) => filter.key !== 'type')
		: filters,
)

const filters: ListViewFilter[] = [
	{
		key: 'type',
		label: 'Type',
		options: Object.entries(SNAPSHOT_TYPE_LABEL).map(([value, label]) => ({
			label,
			value,
		})),
	},
	{
		key: 'status',
		label: 'Status',
		options: ['Pending', 'Available', 'Failed'].map((value) => ({
			label: value,
			value,
		})),
	},
]

interface SnapshotAction {
	label: string
	icon: string
	theme?: 'red'
	onClick: () => void
}

function rowActions(row: VMSnapshotRow): SnapshotAction[] {
	// A member can be scoped to some servers, so each row checks its own server.
	if (!row.capabilities.includes('server:snapshot') || row.status === 'Pending')
		return []
	const actions: SnapshotAction[] = []
	if (props.canRestore && row.status === 'Available' && row.is_restorable)
		actions.push({
			label: 'Restore to a new server',
			icon: 'lucide-server',
			onClick: () => emit('restore', row),
		})
	if (row.status === 'Available' && row.expires_at)
		actions.push({
			label: 'Keep this snapshot',
			icon: 'lucide-archive',
			onClick: () => emit('keep', row),
		})
	actions.push({
		label: 'Delete',
		icon: 'lucide-trash-2',
		theme: 'red',
		onClick: () => emit('delete', [row]),
	})
	return actions
}
</script>

<template>
	<ListView
		v-model:query="query"
		:rows="snapshots"
		:columns="columns"
		:row-key="(row) => row.name"
		:loading="loading"
		:error="error"
		:filters="snapshots.length ? visibleFilters : []"
		:selectable="canManage"
		:searchable="snapshots.length > 0"
		:search-placeholder="searchPlaceholder"
		:show-count="!serverScoped"
		item-label="snapshot"
		row-class="min-h-12 py-1.5"
		:empty-state="{
			title: 'No snapshots yet',
			description: isAccessLocked
				? ACCESS_LOCKED_REASON
				: canManage
					? 'Take a snapshot to save a copy of a server disk that you can use to create another server.'
					: 'Snapshots save a copy of a server disk. Ask a team admin to take one or grant you permission to manage snapshots.',
		}"
		@retry="emit('retry')"
	>
		<template v-if="snapshots.length" #toolbar>
			<Tooltip :text="pricingRule">
				<span
					tabindex="0"
					class="flex items-center gap-1.5 rounded-4 text-p-sm text-ink-gray-7 focus-visible:outline focus-visible:outline-2 focus-visible:outline-outline-gray-3"
				>
					{{ monthlyTotal }}
					<span
						class="lucide-info size-3.5 text-ink-gray-4"
						aria-hidden="true"
					/>
				</span>
			</Tooltip>
			<Button
				v-if="canManage"
				variant="subtle"
				icon-left="lucide-plus"
				label="Take snapshot"
				@click="emit('take')"
			/>
		</template>
		<template v-if="canManage" #empty-action>
			<Button
				variant="subtle"
				icon-left="lucide-plus"
				label="Take snapshot"
				@click="emit('take')"
			/>
		</template>

		<template #selection-actions="{ rows, clear }">
			<Button
				theme="red"
				variant="subtle"
				icon-left="lucide-trash-2"
				:label="`Delete ${rows.length}`"
				@click="
					() => {
						emit('delete', rows)
						clear()
					}
				"
			/>
		</template>

		<template #snapshot="{ row }">
			<div class="min-w-0">
				<p class="truncate text-sm-medium text-ink-gray-8">{{ row.title }}</p>
				<p v-if="!serverScoped" class="truncate text-p-sm text-ink-gray-5">
					{{ row.server_title }}
					· {{ row.region }}
				</p>
			</div>
		</template>

		<template #type="{ row }">
			<span class="text-p-sm text-ink-gray-7">
				{{ SNAPSHOT_TYPE_LABEL[row.snapshot_type] }}
			</span>
		</template>

		<template #size="{ row }">
			<span class="tabular-nums text-p-sm text-ink-gray-7">
				{{ row.status === 'Available' ? `${row.size_gib} GB` : '—' }}
			</span>
		</template>

		<template #created="{ row }">
			<span class="text-p-sm text-ink-gray-7"
				>{{ formatDate(row.creation) }}</span
			>
		</template>

		<template #cost="{ row }">
			<span
				class="truncate text-p-sm text-ink-gray-7"
				:title="row.status === 'Available' ? snapshotCostLabel(row, currency) : undefined"
			>
				{{ row.status === 'Available' ? snapshotCostLabel(row, currency) : '—' }}
			</span>
		</template>

		<template #status="{ row }">
			<Button
				v-if="row.error_detail"
				variant="ghost"
				:theme="row.status === 'Failed' ? 'red' : 'gray'"
				:label="row.status"
				tooltip="View snapshot error"
				@click.stop="errorSnapshot = row"
			/>
			<Badge
				v-else
				:theme="SNAPSHOT_STATUS_THEME[row.status]"
				variant="subtle"
				:label="row.status"
			/>
		</template>

		<template #actions="{ row }">
			<RowActionsMenu :options="rowActions(row)" label="Snapshot actions" />
		</template>
	</ListView>
	<Dialog v-model:open="errorOpen" title="Snapshot error">
		<p class="whitespace-pre-wrap break-words text-p-base text-ink-gray-8">
			{{ errorSnapshot?.error_detail }}
		</p>
	</Dialog>
</template>
