<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import BucketQuotaDialog from '@/components/addons/storage/BucketQuotaDialog.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import UsageMeter from '@/components/servers/overview/UsageMeter.vue'
import { bucketLabel, useObjectStorage } from '@/composables/useObjectStorage'
import { copyToClipboard } from '@/lib/clipboard'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
import { formatDate } from '@/lib/format'
import type { BucketCredentials, StorageBucket } from '@/types/storage'

interface Props {
	region: string
	canManage: boolean
}

defineProps<Props>()
const bucket = defineModel<StorageBucket | null>({ required: true })
const emit = defineEmits<{ rotated: [credentials: BucketCredentials] }>()

const {
	usage,
	usageLoading,
	usageError,
	loadUsage,
	rotateCredentials,
	deleteBucket,
} = useObjectStorage()

watch(
	() => bucket.value?.name,
	(name) => name && loadUsage(name),
	{ immediate: true },
)

const formatBytes = (bytes: number): string => {
	const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
	const exponent = Math.min(
		Math.floor(Math.log(Math.max(bytes, 1)) / Math.log(1024)),
		units.length - 1,
	)
	const value = bytes / 1024 ** exponent
	return `${value.toFixed(value < 10 && exponent ? 1 : 0)} ${units[exponent]}`
}

const meters = computed(() => {
	const current = usage.value
	if (!current) return []

	const count = current.object_count.toLocaleString()
	return [
		{
			label: 'Stored',
			value: current.quota_bytes
				? `${formatBytes(current.used_bytes)} of ${formatBytes(current.quota_bytes)}`
				: formatBytes(current.used_bytes),
			percent: current.quota_bytes
				? Math.min((current.used_bytes / current.quota_bytes) * 100, 100)
				: null,
		},
		{
			label: 'Objects',
			value: current.quota_objects
				? `${count} of ${current.quota_objects.toLocaleString()}`
				: count,
			percent: current.quota_objects
				? Math.min((current.object_count / current.quota_objects) * 100, 100)
				: null,
		},
	]
})

const connection = computed(() =>
	bucket.value
		? [
				{ label: 'Endpoint', value: bucket.value.endpoint_url },
				{ label: 'Bucket', value: bucket.value.bucket_name },
				{ label: 'Access key', value: bucket.value.access_key },
			]
		: [],
)

const copy = async (value: string, label: string): Promise<void> => {
	if (await copyToClipboard(value)) {
		successToast(`${label} copied`)
		return
	}

	reportError(`${label} could not be copied. Select it and copy by hand.`)
}

const quotaTarget = ref<StorageBucket | null>(null)
const rotateTarget = ref<StorageBucket | null>(null)
const deleteTarget = ref<StorageBucket | null>(null)
const busy = ref(false)
const actionError = ref('')

const rotate = async (target: StorageBucket): Promise<void> => {
	busy.value = true
	actionError.value = ''
	try {
		emit('rotated', await rotateCredentials(target.name))
		rotateTarget.value = null
	} catch (e) {
		actionError.value = getErrorMessage(e, "The key couldn't be rotated.")
	} finally {
		busy.value = false
	}
}

const remove = async (target: StorageBucket): Promise<void> => {
	busy.value = true
	actionError.value = ''
	try {
		await deleteBucket(target.name)
		deleteTarget.value = null
		bucket.value = null
	} catch (e) {
		actionError.value = getErrorMessage(e, "The bucket couldn't be deleted.")
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<SidePanel
		:open="!!bucket"
		@update:open="(open: boolean) => !open && (bucket = null)"
	>
		<template #title>
			<p v-if="bucket" class="truncate text-base-semibold text-ink-gray-9">
				{{ bucketLabel(bucket) }}
			</p>
		</template>
		<template #subtitle>
			<p v-if="bucket" class="truncate text-p-sm text-ink-gray-5">
				{{ region }}
				· Created {{ formatDate(bucket.creation) }}
			</p>
		</template>

		<div v-if="bucket" class="divide-y divide-outline-gray-1">
			<section class="space-y-4 p-4" :aria-busy="usageLoading">
				<h3 class="text-sm-medium text-ink-gray-5">Usage</h3>

				<template v-if="usageLoading && !usage">
					<div class="h-7 animate-pulse rounded-4 bg-surface-gray-2" />
					<div class="h-7 animate-pulse rounded-4 bg-surface-gray-2" />
				</template>

				<div
					v-else-if="usageError"
					class="flex items-center justify-between gap-3 text-p-sm text-ink-gray-5"
				>
					Usage couldn't load.
					<Button
						variant="ghost"
						size="sm"
						label="Retry"
						@click="loadUsage(bucket.name)"
					/>
				</div>

				<template v-for="meter in meters" v-else :key="meter.label">
					<UsageMeter
						v-if="meter.percent !== null"
						:label="meter.label"
						:value="meter.value"
						:percent="meter.percent"
					/>
					<p
						v-else
						class="flex items-center justify-between gap-4 text-sm text-ink-gray-6"
					>
						{{ meter.label }}
						<span class="font-medium tabular-nums text-ink-gray-9">
							{{ meter.value }}
						</span>
					</p>
				</template>
			</section>

			<section class="space-y-3 p-4">
				<h3 class="text-sm-medium text-ink-gray-5">Connection</h3>

				<dl class="space-y-1">
					<div
						v-for="row in connection"
						:key="row.label"
						class="group -mx-2 flex items-center gap-3 rounded-4 px-2 py-1.5 hover:bg-surface-gray-2"
					>
						<dt class="w-20 shrink-0 text-sm text-ink-gray-5">
							{{ row.label }}
						</dt>
						<dd
							class="min-w-0 flex-1 truncate font-mono text-sm text-ink-gray-8"
						>
							{{ row.value }}
						</dd>
						<Button
							variant="ghost"
							size="sm"
							icon="lucide-copy"
							:label="`Copy ${row.label.toLowerCase()}`"
							tooltip="Copy"
							class="opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"
							@click="copy(row.value, row.label)"
						/>
					</div>
				</dl>

				<p v-if="!bucket.is_managed" class="text-p-sm text-ink-gray-5">
					The secret key is shown once, when the bucket is created or its key is
					rotated.
				</p>
			</section>

			<p v-if="bucket.is_managed" class="p-4 text-p-sm text-ink-gray-6">
				Your servers in this region write their backups here. Frappe Cloud
				manages its key and limits, so it can't be changed or deleted.
			</p>
		</div>

		<template v-if="bucket && canManage && !bucket.is_managed" #footer>
			<div class="flex flex-wrap gap-2">
				<Button
					icon-left="lucide-gauge"
					label="Set quota"
					@click="quotaTarget = bucket"
				/>
				<Button
					icon-left="lucide-refresh-cw"
					label="Rotate key"
					@click="rotateTarget = bucket"
				/>
				<Button
					class="ml-auto"
					theme="red"
					icon-left="lucide-trash-2"
					label="Delete"
					@click="deleteTarget = bucket"
				/>
			</div>
		</template>
	</SidePanel>

	<BucketQuotaDialog v-model="quotaTarget" :usage="usage" />

	<ConfirmDialog
		v-model:target="rotateTarget"
		title="Rotate key"
		confirm-label="Rotate key"
		size="md"
		:loading="busy"
		:error="actionError"
		@confirm="rotate"
		@after-leave="actionError = ''"
	>
		<p v-if="rotateTarget" class="text-p-base text-ink-gray-7">
			Issue a new key for
			<span class="text-base-semibold text-ink-gray-9"
				>{{ bucketLabel(rotateTarget) }}</span
			>? Anything that uses the current key stops working at once.
		</p>
	</ConfirmDialog>

	<ConfirmDialog
		v-model:target="deleteTarget"
		title="Delete bucket"
		confirm-label="Delete bucket"
		theme="red"
		size="md"
		:loading="busy"
		:error="actionError"
		@confirm="remove"
		@after-leave="actionError = ''"
	>
		<p v-if="deleteTarget" class="text-p-base text-ink-gray-7">
			Delete
			<span class="text-base-semibold text-ink-gray-9"
				>{{ bucketLabel(deleteTarget) }}</span
			>? Empty it first: a bucket that still holds objects can't be deleted.
		</p>
	</ConfirmDialog>
</template>
