<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, h, ref, watch } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import { useBucketObjects } from '@/composables/useBucketObjects'
import { formatBytes } from '@/lib/bytes'
import { formatDateTime, timeAgo } from '@/lib/datetime'
import { getErrorMessage, reportError } from '@/lib/feedback'
import type { StorageBucket } from '@/types/storage'

interface Props {
	bucket: StorageBucket
	canDownload: boolean
}

interface FileRow {
	key: string
	name: string
	isFolder: boolean
	size: number
	modified: string
}

const props = defineProps<Props>()

const { objects, folders, nextOffset, loading, error, load, loadMore, getDownloadUrl } =
	useBucketObjects()

const prefix = ref('')
const query = ref(createListViewQuery({ pageSize: 50 }))

watch(
	[() => props.bucket.name, prefix],
	([name, path]) => {
		query.value = createListViewQuery({ pageSize: 50 })
		load(name, path)
	},
	{ immediate: true },
)

const crumbs = computed(() => {
	const parts = prefix.value.split('/').filter(Boolean)
	return parts.map((part, index) => ({
		label: part,
		prefix: `${parts.slice(0, index + 1).join('/')}/`,
	}))
})

const rows = computed<FileRow[]>(() => [
	...folders.value.map((folder) => ({
		key: folder,
		name: folder.slice(prefix.value.length).replace(/\/$/, ''),
		isFolder: true,
		size: -1,
		modified: '',
	})),
	...objects.value
		.filter((item) => item.key !== prefix.value)
		.map((item) => ({
			key: item.key,
			name: item.key.slice(prefix.value.length),
			isFolder: false,
			size: item.size_bytes,
			modified: item.last_modified,
		})),
])

const downloading = ref('')

const download = async (key: string): Promise<void> => {
	downloading.value = key
	try {
		window.open(await getDownloadUrl(props.bucket.name, key), '_blank')
	} catch (failure) {
		reportError(getErrorMessage(failure, "The download link couldn't be created."))
	} finally {
		downloading.value = ''
	}
}

const columns = computed<ListViewColumn<FileRow>[]>(() => [
	{
		accessorKey: 'name',
		header: 'Name',
		size: 500,
		cell: ({ row }) =>
			h('span', { class: 'flex min-w-0 items-center gap-2.5' }, [
				h('span', {
					class: [
						row.original.isFolder ? 'lucide-folder' : 'lucide-file',
						'size-4 shrink-0 text-ink-gray-5',
					],
					'aria-hidden': 'true',
				}),
				h('span', { class: 'truncate text-sm text-ink-gray-8' }, row.original.name),
			]),
	},
	{
		accessorKey: 'size',
		header: 'Size',
		size: 100,
		meta: { align: 'end' },
		cell: ({ row }) =>
			h(
				'span',
				{ class: 'text-sm tabular-nums text-ink-gray-6' },
				row.original.isFolder ? '' : formatBytes(row.original.size),
			),
	},
	{
		accessorKey: 'modified',
		header: 'Last modified',
		size: 140,
		cell: ({ row }) =>
			h(
				'span',
				{
					class: 'whitespace-nowrap text-sm text-ink-gray-6',
					title: row.original.modified ? formatDateTime(row.original.modified) : '',
				},
				row.original.modified ? timeAgo(row.original.modified) : '',
			),
	},
	...(props.canDownload
		? [
				{
					id: 'actions',
					header: '',
					enableSorting: false,
					meta: { align: 'end' },
					cell: ({ row }) =>
						row.original.isFolder
							? null
							: h(Button, {
									variant: 'ghost',
									icon: 'lucide-download',
									label: `Download ${row.original.name}`,
									tooltip: 'Download',
									loading: downloading.value === row.original.key,
									onClick: (event: MouseEvent) => {
										event.stopPropagation()
										download(row.original.key)
									},
								}),
				} satisfies ListViewColumn<FileRow>,
			]
		: []),
])

const open = (row: FileRow): void => {
	if (row.isFolder) prefix.value = row.key
}
</script>

<template>
	<div class="space-y-3">
		<nav
			v-if="prefix"
			aria-label="Folder"
			class="flex min-w-0 flex-wrap items-center gap-1 text-sm text-ink-gray-5"
		>
			<button
				type="button"
				aria-label="All files"
				class="grid size-6 place-items-center rounded-4 hover:bg-surface-gray-2 hover:text-ink-gray-8"
				@click="prefix = ''"
			>
				<span class="lucide-house size-4" aria-hidden="true" />
			</button>
			<template v-for="crumb in crumbs" :key="crumb.prefix">
				<span aria-hidden="true">/</span>
				<button
					type="button"
					class="rounded-4 px-1 hover:bg-surface-gray-2 hover:text-ink-gray-8 last:text-ink-gray-8"
					@click="prefix = crumb.prefix"
				>
					{{ crumb.label }}
				</button>
			</template>
		</nav>

		<ListView
			v-model:query="query"
			:rows="rows"
			:columns="columns"
			:row-key="(row) => row.key"
			:loading="loading && !rows.length"
			:error="error"
			searchable
			:search-placeholder="prefix ? `Search ${prefix}` : 'Search this bucket'"
			item-label="item"
			:empty-state="{
				title: prefix ? 'This folder is empty' : 'No files yet',
				description: 'Upload with any S3 client, using the details under Settings.',
			}"
			@retry="load(bucket.name, prefix)"
			@row-click="open"
		/>

		<div v-if="nextOffset" class="flex justify-center">
			<Button
				label="Load more"
				:loading="loading"
				@click="loadMore(bucket.name, prefix)"
			/>
		</div>
	</div>
</template>
