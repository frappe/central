<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import type { TeamSSHKey } from '@/types/sshKeys'

interface Props {
	keys: TeamSSHKey[]
	loading: boolean
	error: string
	canManage: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
	add: []
	retryLoad: []
	retrySync: [key: TeamSSHKey]
	rotate: [key: TeamSSHKey]
	delete: [key: TeamSSHKey]
}>()

const query = ref(createListViewQuery())
const columns = computed<ListViewColumn<TeamSSHKey>[]>(() => [
	{
		id: 'key',
		accessorFn: (key) => `${key.title} ${key.fingerprint}`,
		header: 'Key',
	},
	{ id: 'servers', accessorKey: 'server_count', header: 'Servers', size: 120 },
	{
		id: 'actions',
		header: '',
		size: 48,
		enableSorting: false,
		enableGlobalFilter: false,
		meta: { align: 'end' },
	},
])

function actions(key: TeamSSHKey) {
	if (!props.canManage) return []
	return [
		...(key.last_sync_error
			? [
					{
						label: 'Retry sync',
						icon: 'lucide-refresh-cw',
						onClick: () => emit('retrySync', key),
					},
				]
			: []),
		{
			label: 'Rotate key',
			icon: 'lucide-refresh-cw',
			onClick: () => emit('rotate', key),
		},
		...(key.server_count
			? []
			: [
					{
						label: 'Delete',
						icon: 'lucide-trash-2',
						theme: 'red' as const,
						onClick: () => emit('delete', key),
					},
				]),
	]
}
</script>

<template>
	<ListView
		v-model:query="query"
		:rows="keys"
		:columns="columns"
		:row-key="(key) => key.name"
		:loading="loading"
		:error="error"
		:searchable="keys.length > 0"
		search-placeholder="Search SSH keys…"
		item-label="key"
		row-class="min-h-12 py-1.5"
		:show-count="false"
		:empty-state="{
			title: 'No SSH Keys yet',
			description: 'Add a public key, then add it when creating servers.',
		}"
		@retry="emit('retryLoad')"
	>
		<template v-if="keys.length && canManage" #toolbar>
			<Button
				variant="subtle"
				label="Add SSH Key"
				icon-left="lucide-plus"
				@click="emit('add')"
			/>
		</template>
		<template v-if="canManage" #empty-action>
			<Button
				variant="subtle"
				label="Add SSH Key"
				icon-left="lucide-plus"
				@click="emit('add')"
			/>
		</template>
		<template #key="{ row }">
			<div class="min-w-0">
				<p class="truncate text-sm-medium text-ink-gray-8">{{ row.title }}</p>
				<p class="truncate font-mono text-p-sm text-ink-gray-5">
					{{ row.fingerprint }}
				</p>
				<p v-if="row.last_sync_error" class="truncate text-p-sm text-ink-red-6">
					{{ row.last_sync_error }}
				</p>
			</div>
		</template>
		<template #servers="{ row }">
			<span class="tabular-nums text-p-sm text-ink-gray-7"
				>{{ row.server_count }}</span
			>
		</template>
		<template #actions="{ row }">
			<RowActionsMenu :options="actions(row)" label="SSH key actions" />
		</template>
	</ListView>
</template>
