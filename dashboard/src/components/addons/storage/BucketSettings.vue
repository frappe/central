<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import BucketQuotaDialog from '@/components/addons/storage/BucketQuotaDialog.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import UsageMeter from '@/components/servers/overview/UsageMeter.vue'
import { bucketLabel, useObjectStorage } from '@/composables/useObjectStorage'
import { copyToClipboard } from '@/lib/clipboard'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
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

			<div
				v-if="usageLoading && !usage"
				class="h-9 animate-pulse rounded-4 bg-surface-gray-2"
			/>

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
				<template v-for="meter in meters" :key="meter.label">
					<UsageMeter
						v-if="meter.percent !== null"
						:label="meter.label"
						:value="meter.value"
						:percent="meter.percent"
						class="rounded-6 bg-surface-gray-1 p-4"
					/>

					<p
						v-else
						class="flex items-center justify-between gap-4 rounded-6 bg-surface-gray-1 p-4 text-sm text-ink-gray-6"
					>
						{{ meter.label }}
						<span class="text-sm-medium tabular-nums text-ink-gray-9">
							{{ meter.value }}
						</span>
					</p>
				</template>
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
					<dt class="w-24 shrink-0 text-sm text-ink-gray-5">
						{{ row.label }}
					</dt>

					<dd class="min-w-0 flex-1 truncate font-mono text-sm text-ink-gray-8">
						{{ row.value }}
					</dd>

					<Button
						variant="ghost"
						icon="lucide-copy"
						:label="`Copy ${row.label.toLowerCase()}`"
						tooltip="Copy"
						@click="copy(row.value, row.label)"
					/>
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
