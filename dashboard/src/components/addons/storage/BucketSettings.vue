<script setup lang="ts">
import { Button, Skeleton } from 'frappe-ui'
import { computed, ref } from 'vue'
import BucketQuotaDialog from '@/components/addons/storage/BucketQuotaDialog.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import CopyButton from '@/components/common/CopyButton.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import UsageCard from '@/components/common/UsageCard.vue'
import { bucketLabel, useObjectStorage } from '@/composables/useObjectStorage'
import { getErrorMessage } from '@/lib/feedback'
import type { BucketCredentials, StorageBucket } from '@/types/storage'

interface Props {
	bucket: StorageBucket
	canManage: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
	rotated: [credentials: BucketCredentials]
	deleted: []
}>()

const {
	usage,
	usageLoading,
	usageError,
	loadUsage,
	rotateCredentials,
	deleteBucket,
} = useObjectStorage()

const formatBytes = (bytes: number): string => {
	const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
	const exponent = Math.min(
		Math.floor(Math.log(Math.max(bytes, 1)) / Math.log(1024)),
		units.length - 1,
	)
	const value = bytes / 1024 ** exponent
	return `${value.toFixed(value < 10 && exponent ? 1 : 0)} ${units[exponent]}`
}

const percentOf = (used: number, limit: number | null): number | null =>
	limit ? Math.min(Math.round((used / limit) * 100), 100) : null

const meters = computed(() => {
	const current = usage.value
	if (!current) return []

	return [
		{
			label: 'Stored',
			icon: 'lucide-hard-drive',
			used: formatBytes(current.used_bytes),
			limit: current.quota_bytes ? formatBytes(current.quota_bytes) : null,
			percent: percentOf(current.used_bytes, current.quota_bytes),
		},
		{
			label: 'Objects',
			icon: 'lucide-files',
			used: current.object_count.toLocaleString(),
			limit: current.quota_objects?.toLocaleString(),
			percent: percentOf(current.object_count, current.quota_objects),
		},
	]
})

const connection = computed(() => [
	{ label: 'Endpoint', value: props.bucket.endpoint_url },
	{ label: 'Bucket', value: props.bucket.bucket_name },
	{ label: 'Access key', value: props.bucket.access_key },
])

const quotaSummary = computed(() =>
	usage.value?.quota_bytes
		? `Current quota: ${formatBytes(usage.value.quota_bytes)} · ${usage.value.quota_objects?.toLocaleString() ?? 'any number of'} objects`
		: 'No quota is set, so the bucket grows as you upload.',
)

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
		emit('deleted')
	} catch (e) {
		actionError.value = getErrorMessage(e, "The bucket couldn't be deleted.")
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<div class="divide-y divide-outline-gray-1">
		<SettingsSection
			title="Quota"
			:help="`Cap how much this bucket can hold. ${quotaSummary}`"
			:aria-busy="usageLoading"
		>
			<template v-if="canManage" #actions>
				<Button label="Set quota" @click="quotaTarget = bucket" />
			</template>

			<Skeleton v-if="usageLoading && !usage" class="h-9 rounded-4" />

			<div
				v-else-if="usageError"
				class="flex items-center justify-between gap-3 text-sm text-ink-gray-5"
			>
				Usage couldn't load.
				<Button
					variant="ghost"
					size="sm"
					label="Retry"
					@click="loadUsage(bucket.name)"
				/>
			</div>

			<div v-else class="grid gap-3 md:grid-cols-2 md:gap-4">
				<UsageCard v-for="meter in meters" :key="meter.label" v-bind="meter" />
			</div>
		</SettingsSection>

		<SettingsSection
			title="Connection"
			help="Point any S3 client at these. The secret key is shown once, when the bucket is created or its key is rotated."
		>
			<template v-if="canManage" #actions>
				<Button label="Rotate key" @click="rotateTarget = bucket" />
			</template>

			<dl class="space-y-1">
				<div
					v-for="row in connection"
					:key="row.label"
					class="flex items-center gap-3"
				>
					<dt class="w-24 shrink-0 text-sm text-ink-gray-5">{{ row.label }}</dt>

					<dd class="min-w-0 truncate font-mono text-sm text-ink-gray-8">
						{{ row.value }}
					</dd>

					<CopyButton :text="row.value" />
				</div>
			</dl>
		</SettingsSection>

		<SettingsSection
			v-if="canManage"
			title="Delete bucket"
			help="Removes the bucket and its key for good. Empty it first: a bucket that still holds objects can't be deleted."
		>
			<template #actions>
				<Button
					theme="red"
					label="Delete bucket"
					@click="deleteTarget = bucket"
				/>
			</template>
		</SettingsSection>

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
	</div>
</template>
