<script setup lang="ts">
import { Button, Tooltip } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import { PAGE_SIZE, useBucketObjects } from '@/composables/useBucketObjects'
import { formatBytes } from '@/lib/bytes'
import { formatDateTime, timeAgo } from '@/lib/datetime'
import { getErrorMessage, reportError } from '@/lib/feedback'
import type { StorageBucket } from '@/types/storage'

interface Props {
	bucket: StorageBucket
	canDownload: boolean
}

interface FileRow {
	id: string
	name: string
	isFolder: boolean
	size: string
	modified: string
	modifiedTitle: string
}

const props = defineProps<Props>()

const {
	objects,
	folders,
	page,
	hasNext,
	loading,
	error,
	load,
	next,
	previous,
	retry,
	getDownloadUrl,
} = useBucketObjects()

const prefix = ref('')
const selecting = ref(false)
const downloading = ref('')

const query = ref(createListViewQuery({ pageSize: PAGE_SIZE }))
const searchPrefix = computed(() => prefix.value + query.value.search.trim())

watch(
	[() => props.bucket.name, prefix],
	() => (query.value = createListViewQuery({ pageSize: PAGE_SIZE })),
)

watch(
	[() => props.bucket.name, searchPrefix],
	([name, path]) => load(name, path),
	{ immediate: true },
)

const crumbs = computed(() => {
	const parts = prefix.value.split('/').filter(Boolean)

	return parts.map((part, index) => ({
		label: part,
		prefix: `${parts.slice(0, index + 1).join('/')}/`,
	}))
})

const searchPlaceholder = computed(() =>
	prefix.value
		? `Search in ${crumbs.value[crumbs.value.length - 1].label}`
		: 'Search by name',
)

const emptyState = computed(() => ({
	title: prefix.value ? 'This folder is empty' : 'No files yet',
	description: 'Upload with any S3 client, using the details under Settings.',
}))

const folderRows = computed<FileRow[]>(() =>
	folders.value.map((folder) => ({
		id: folder,
		name: folder.slice(prefix.value.length).replace(/\/$/, ''),
		isFolder: true,
		size: '',
		modified: '',
		modifiedTitle: '',
	})),
)

const fileRows = computed<FileRow[]>(() =>
	objects.value
		.filter((item) => item.key !== prefix.value)
		.map((item) => ({
			id: item.key,
			name: item.key.slice(prefix.value.length),
			isFolder: false,
			size: formatBytes(item.size_bytes),
			modified: timeAgo(item.last_modified),
			modifiedTitle: formatDateTime(item.last_modified),
		})),
)

const rows = computed(() => [...folderRows.value, ...fileRows.value])

const columns = computed<ListViewColumn<FileRow>[]>(() => [
	{ accessorKey: 'name', header: 'Name', size: 500, enableSorting: false },
	{ accessorKey: 'size', header: 'Size', size: 100, enableSorting: false },
	{
		accessorKey: 'modified',
		header: 'Last modified',
		size: 140,
		enableSorting: false,
	},
	...(props.canDownload
		? [{ id: 'actions', header: '', size: 40, enableSorting: false }]
		: []),
])

const download = async (key: string): Promise<void> => {
	downloading.value = key

	try {
		window.open(await getDownloadUrl(props.bucket.name, key), '_blank')
	} catch (failure) {
		reportError(
			getErrorMessage(failure, "The download link couldn't be created."),
		)
	} finally {
		downloading.value = ''
	}
}
</script>

<template>
	<div class="flex flex-col gap-3">
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
			class="flex min-h-0 flex-1 flex-col"
			:rows="rows"
			:columns="columns"
			:row-key="(row) => row.id"
			:loading="loading"
			:error="error"
			searchable
			:selectable="selecting"
			server-side
			:paginated="false"
			:show-count="false"
			:search-placeholder="searchPlaceholder"
			:empty-state="emptyState"
			@retry="retry(bucket.name, searchPrefix)"
		>
			<template #toolbar>
				<Button
					:label="selecting ? 'Done' : 'Select'"
					@click="selecting = !selecting"
				/>

				<Tooltip text="Uploading from the dashboard is coming soon">
					<Button
						variant="solid"
						icon-left="lucide-upload"
						label="Upload"
						disabled
					/>
				</Tooltip>
			</template>

			<template #selection-actions>
				<Tooltip text="Deleting from the dashboard is coming soon">
					<Button
						theme="red"
						icon-left="lucide-trash-2"
						label="Delete"
						disabled
					/>
				</Tooltip>
			</template>

			<template #name="{ row }">
				<span class="flex min-w-0 items-center gap-2.5 text-sm text-ink-gray-8">
					<span
						:class="row.isFolder ? 'lucide-folder' : 'lucide-file'"
						class="size-4 shrink-0 text-ink-gray-5"
					/>

					<button
						v-if="row.isFolder"
						type="button"
						class="truncate hover:underline"
						@click.stop="prefix = row.id"
					>
						{{ row.name }}
					</button>

					<span v-else class="truncate">{{ row.name }}</span>
				</span>
			</template>

			<template #size="{ row }">
				<span class="text-sm tabular-nums text-ink-gray-6">
					{{ row.size }}
				</span>
			</template>

			<template #modified="{ row }">
				<span class="text-sm text-ink-gray-6" :title="row.modifiedTitle">
					{{ row.modified }}
				</span>
			</template>

			<template #actions="{ row }">
				<Button
					v-if="!row.isFolder"
					variant="ghost"
					icon="lucide-download"
					:label="`Download ${row.name}`"
					tooltip="Download"
					:loading="downloading === row.id"
					@click.stop="download(row.id)"
				/>
			</template>
		</ListView>

		<footer
			v-if="page > 0 || hasNext"
			class="flex items-center justify-between gap-3"
		>
			<span class="text-sm text-ink-gray-5">
				Page {{ page + 1 }} · {{ PAGE_SIZE }} per page
			</span>

			<div class="flex gap-2">
				<Button
					icon="lucide-chevron-left"
					label="Previous page"
					:disabled="page === 0 || loading"
					@click="previous(bucket.name, searchPrefix)"
				/>

				<Button
					icon="lucide-chevron-right"
					label="Next page"
					:disabled="!hasNext || loading"
					@click="next(bucket.name, searchPrefix)"
				/>
			</div>
		</footer>
	</div>
</template>
