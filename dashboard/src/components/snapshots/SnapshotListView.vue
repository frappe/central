<script setup lang="ts">
import { Badge, Button, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
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
	/** The viewer holds server:snapshot, so rows can be kept, deleted and restored. */
	canManage: boolean
	/** How many of each server's newest snapshots are free. */
	freePerServer: number
	/** Search to open with, such as the server a link came from. */
	initialSearch?: string
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

const freeRule = computed(
	() =>
		`The ${props.freePerServer} newest snapshots of each server are free. Each older one costs money by its size, per month.`,
)
const monthlyTotal = computed(() => {
	const total = props.snapshots.reduce(
		(sum, row) => sum + (row.is_billed ? (row.monthly_cost ?? 0) : 0),
		0,
	)
	return total
		? `${money(total, props.currency, { trimTrailingZeros: true })} / month`
		: 'All free'
})

const columns = computed<ListViewColumn<VMSnapshotRow>[]>(() => [
	{
		id: 'snapshot',
		accessorFn: (row) => `${row.title} ${row.server_title}`,
		header: 'Snapshot',
		size: 280,
	},
	{
		id: 'type',
		accessorFn: (row) => row.snapshot_type,
		header: 'Type',
		size: 140,
	},
	{
		id: 'size',
		accessorFn: (row) => row.size_mib,
		header: 'Size',
		size: 90,
		meta: { align: 'end' },
	},
	{
		id: 'created',
		accessorFn: (row) => row.creation,
		header: 'Created',
		size: 120,
		meta: { cellClass: 'max-md:hidden', headerClass: 'max-md:hidden' },
	},
	{
		id: 'cost',
		accessorFn: (row) => snapshotCostLabel(row, props.currency),
		header: 'Cost',
		size: 170,
		enableSorting: false,
	},
	{
		accessorKey: 'status',
		header: 'Status',
		size: 110,
	},
	{
		id: 'actions',
		header: '',
		size: 48,
		enableSorting: false,
		enableGlobalFilter: false,
		meta: { align: 'end' },
	},
])

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
	if (!props.canManage || row.status === 'Pending') return []
	const actions: SnapshotAction[] = []
	if (row.status === 'Available' && row.is_restorable)
		actions.push({
			label: 'Create server from this',
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
		:filters="snapshots.length ? filters : []"
		:selectable="canManage"
		:searchable="snapshots.length > 0"
		search-placeholder="Search by snapshot or server name"
		item-label="snapshot"
		row-class="min-h-12 py-1.5"
		:empty-state="{
			title: 'No snapshots yet',
			description: 'Take a snapshot of a server to save its disk.',
		}"
		@retry="emit('retry')"
	>
		<template v-if="snapshots.length" #toolbar>
			<Tooltip :text="freeRule">
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
				<p class="truncate text-p-sm text-ink-gray-5">
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
			<span class="text-p-sm text-ink-gray-7">
				{{ row.status === 'Available' ? snapshotCostLabel(row, currency) : '—' }}
			</span>
		</template>

		<template #status="{ row }">
			<Tooltip
				:text="row.error_detail || undefined"
				:disabled="!row.error_detail"
			>
				<Badge
					:theme="SNAPSHOT_STATUS_THEME[row.status]"
					variant="subtle"
					:label="row.status"
				/>
			</Tooltip>
		</template>

		<template #actions="{ row }">
			<RowActionsMenu :options="rowActions(row)" label="Snapshot actions" />
		</template>
	</ListView>
</template>
