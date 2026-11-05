<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, markRaw, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import {
	MAXIMUM_UPLOAD_BYTES,
	PAGE_SIZE,
	useBucketObjects,
} from '@/composables/useBucketObjects'
import { formatBytes } from '@/lib/bytes'
import { formatDateTime, timeAgo } from '@/lib/datetime'
import {
	getErrorMessage,
	isAbortError,
	reportError,
	successToast,
} from '@/lib/feedback'
import type { StorageBucket } from '@/types/storage'

interface Props {
	bucket: StorageBucket
	canManage: boolean
}

interface Upload {
	key: string
	name: string
	progress: number
	error: string
	controller: AbortController
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
	upload,
	remove,
} = useBucketObjects()

const route = useRoute()

const prefix = computed(() => {
	const path = route.query.path

	if (typeof path !== 'string' || !path) return ''

	return path.endsWith('/') ? path : `${path}/`
})

const folderLink = (path: string) => ({
	query: { ...route.query, path: path || undefined },
})

const downloading = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const uploads = ref<Upload[]>([])
const deleteTarget = ref<FileRow[] | null>(null)
const deleting = ref(false)
const deleteError = ref('')
let clearSelection = (): void => {}

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
	description: props.canManage
		? 'Upload files here, or with any S3 client using the details under Settings.'
		: 'Files uploaded to this bucket show here.',
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
	{ key: 'name', label: 'Name' },
	{ key: 'size', label: 'Size', width: '6rem' },
	{ key: 'modified', label: 'Last modified', width: '9rem' },
	...(props.canManage ? [{ key: 'actions', label: '', width: '2.5rem' }] : []),
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

const uploadOne = async (file: File): Promise<void> => {
	uploads.value.push({
		key: prefix.value + file.name,
		name: file.name,
		progress: 0,
		error: '',
		controller: markRaw(new AbortController()),
	})
	// The reactive copy, so progress and errors written to it re-render.
	const row = uploads.value[uploads.value.length - 1]

	if (file.size > MAXIMUM_UPLOAD_BYTES) {
		row.error = 'Files over 5 GB need an S3 client.'
		return
	}

	try {
		await upload(
			props.bucket.name,
			row.key,
			file,
			(fraction) => (row.progress = fraction),
			row.controller.signal,
		)
		uploads.value = uploads.value.filter((item) => item !== row)
		successToast(`Uploaded ${file.name}`)
	} catch (failure) {
		if (isAbortError(failure)) {
			uploads.value = uploads.value.filter((item) => item !== row)
			return
		}
		row.error = getErrorMessage(failure, "The file couldn't upload.")
	}
}

const startUploads = async (event: Event): Promise<void> => {
	const input = event.target as HTMLInputElement
	const files = Array.from(input.files ?? [])
	input.value = ''

	await Promise.all(files.map(uploadOne))
	retry(props.bucket.name, searchPrefix.value)
}

const dismissUpload = (entry: Upload): void => {
	entry.controller.abort()
	uploads.value = uploads.value.filter((item) => item !== entry)
}

const deleteSummary = computed(() => {
	const rows = deleteTarget.value ?? []
	const files = rows.filter((row) => !row.isFolder).length
	const folders = rows.filter((row) => row.isFolder).length
	const parts: string[] = []
	if (files) parts.push(`${files} ${files === 1 ? 'file' : 'files'}`)
	if (folders) parts.push(`${folders} ${folders === 1 ? 'folder' : 'folders'}`)

	return parts.join(' and ')
})

const askDelete = (rows: FileRow[], clear: () => void): void => {
	clearSelection = clear
	deleteError.value = ''
	deleteTarget.value = rows
}

const confirmDelete = async (rows: FileRow[]): Promise<void> => {
	deleting.value = true
	deleteError.value = ''

	try {
		const deleted = await remove(
			props.bucket.name,
			rows.filter((row) => !row.isFolder).map((row) => row.id),
			rows.filter((row) => row.isFolder).map((row) => row.id),
		)
		deleteTarget.value = null
		clearSelection()
		successToast(`Deleted ${deleted} ${deleted === 1 ? 'object' : 'objects'}`)
		retry(props.bucket.name, searchPrefix.value)
	} catch (failure) {
		deleteError.value = getErrorMessage(
			failure,
			"The files couldn't be deleted.",
		)
	} finally {
		deleting.value = false
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
			<RouterLink
				:to="folderLink('')"
				aria-label="All files"
				class="grid size-6 place-items-center rounded-4 hover:bg-surface-gray-2 hover:text-ink-gray-8"
			>
				<span class="lucide-house size-4" aria-hidden="true" />
			</RouterLink>

			<template v-for="crumb in crumbs" :key="crumb.prefix">
				<span aria-hidden="true">/</span>

				<RouterLink
					:to="folderLink(crumb.prefix)"
					class="rounded-4 px-1 hover:bg-surface-gray-2 hover:text-ink-gray-8 last:text-ink-gray-8"
				>
					{{ crumb.label }}
				</RouterLink>
			</template>
		</nav>

		<ul
			v-if="uploads.length"
			aria-label="Uploads"
			class="flex flex-col divide-y divide-outline-gray-1 rounded-lg border border-outline-gray-2"
		>
			<li
				v-for="entry in uploads"
				:key="entry.key"
				class="flex items-center gap-3 px-3 py-2"
			>
				<span class="lucide-upload size-4 shrink-0 text-ink-gray-5" />

				<div class="flex min-w-0 flex-1 flex-col gap-1">
					<span class="truncate text-sm text-ink-gray-8">{{ entry.name }}</span>

					<span v-if="entry.error" class="text-sm text-ink-red-4">
						{{ entry.error }}
					</span>

					<div
						v-else
						role="progressbar"
						:aria-label="`Uploading ${entry.name}`"
						:aria-valuenow="Math.round(entry.progress * 100)"
						aria-valuemin="0"
						aria-valuemax="100"
						class="h-1 overflow-hidden rounded-full bg-surface-gray-2"
					>
						<div
							class="h-full bg-surface-gray-7 transition-[width]"
							:style="{ width: `${entry.progress * 100}%` }"
						/>
					</div>
				</div>

				<span
					v-if="!entry.error"
					class="w-10 text-right text-sm tabular-nums text-ink-gray-6"
				>
					{{ Math.round(entry.progress * 100) }}%
				</span>

				<Button
					variant="ghost"
					icon="lucide-x"
					:label="entry.error ? `Dismiss ${entry.name}` : `Cancel ${entry.name}`"
					:tooltip="entry.error ? 'Dismiss' : 'Cancel'"
					@click="dismissUpload(entry)"
				/>
			</li>
		</ul>

		<ListView
			v-model:query="query"
			class="flex min-h-0 flex-1 flex-col"
			:rows="rows"
			:columns="columns"
			:row-key="(row) => row.id"
			:loading="loading"
			:error="error"
			searchable
			:selectable="canManage"
			server-side
			:paginated="false"
			:show-count="false"
			:search-placeholder="searchPlaceholder"
			:empty-state="emptyState"
			@retry="retry(bucket.name, searchPrefix)"
		>
			<template v-if="canManage" #toolbar>
				<Button
					variant="solid"
					icon-left="lucide-upload"
					label="Upload"
					@click="fileInput?.click()"
				/>

				<input
					ref="fileInput"
					type="file"
					multiple
					class="hidden"
					aria-label="Files to upload"
					@change="startUploads"
				/>
			</template>

			<template #selection-actions="{ rows: selected, clear }">
				<Button
					theme="red"
					icon-left="lucide-trash-2"
					label="Delete"
					@click="askDelete(selected, clear)"
				/>
			</template>

			<template #name="{ row }">
				<span class="flex min-w-0 items-center gap-2.5 text-sm text-ink-gray-8">
					<span
						:class="row.isFolder ? 'lucide-folder' : 'lucide-file'"
						class="size-4 shrink-0 text-ink-gray-5"
					/>

					<RouterLink
						v-if="row.isFolder"
						:to="folderLink(row.id)"
						class="truncate hover:underline"
						@click.stop
					>
						{{ row.name }}
					</RouterLink>

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

		<ConfirmDialog
			v-model:target="deleteTarget"
			title="Delete files"
			confirm-label="Delete"
			theme="red"
			size="md"
			:loading="deleting"
			:error="deleteError"
			@confirm="confirmDelete"
		>
			<p class="text-p-base text-ink-gray-7">
				Delete {{ deleteSummary }}? Everything inside a folder is deleted too.
				This can't be undone.
			</p>
		</ConfirmDialog>
	</div>
</template>
