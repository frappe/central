<script setup lang="ts">
import { Button, Tabs } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BucketFiles from '@/components/addons/storage/BucketFiles.vue'
import BucketSettings from '@/components/addons/storage/BucketSettings.vue'
import CredentialsDialog from '@/components/addons/storage/CredentialsDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { bucketLabel, useObjectStorage } from '@/composables/useObjectStorage'
import { formatBytes } from '@/lib/bytes'
import { copyToClipboard } from '@/lib/clipboard'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
import { regionLabel } from '@/lib/serverMap'
import type { BucketCredentials } from '@/types/storage'

const route = useRoute()
const router = useRouter()
const { setBreadcrumbs } = useBreadcrumbs()
const { canManageServices } = useCapabilities()
const { regions, buckets, loading, error, reload, usage, loadUsage } =
	useObjectStorage()

const bucket = computed(() =>
	buckets.value.find((item) => item.name === route.params.name),
)

watch(
	bucket,
	(current) => {
		setBreadcrumbs([
			{ label: 'Object storage', route: { path: '/object-storage' } },
			{ label: current ? bucketLabel(current) : 'Bucket' },
		])
		if (current) loadUsage(current.name)
	},
	{ immediate: true },
)

const summary = computed(() => {
	const current = bucket.value
	if (!current) return ''
	const region = regions.value.find((r) => r.region === current.region)
	return [
		region ? regionLabel(region) : current.region,
		usage.value && formatBytes(usage.value.used_bytes),
		usage.value && `${usage.value.object_count.toLocaleString()} objects`,
	]
		.filter(Boolean)
		.join(' · ')
})

const tabs = [
	{ label: 'Files', value: 'files', icon: 'lucide-folder' },
	{ label: 'Settings', value: 'settings', icon: 'lucide-settings' },
]
const activeTab = ref('files')
const credentials = ref<BucketCredentials | null>(null)

const copyEndpoint = async (endpoint: string): Promise<void> => {
	if (await copyToClipboard(endpoint)) {
		successToast('Endpoint copied')
		return
	}

	reportError('The endpoint could not be copied. Select it and copy by hand.')
}
</script>

<template>
	<div class="h-full overflow-y-auto">
		<div class="mx-auto w-full max-w-5xl p-3 md:p-4 lg:pt-8">
			<div v-if="loading" class="space-y-3" aria-busy="true">
				<div class="h-8 w-48 animate-pulse rounded-4 bg-surface-gray-2" />
				<div class="h-5 w-72 animate-pulse rounded-4 bg-surface-gray-2" />
			</div>

			<EmptyState
				v-else-if="error && !buckets.length"
				icon="lucide-cloud-off"
				title="Bucket couldn't load"
				:description="getErrorMessage(error, 'Try again in a moment.')"
			>
				<template #action>
					<Button label="Retry" @click="reload" />
				</template>
			</EmptyState>

			<EmptyState
				v-else-if="!bucket"
				icon="lucide-archive"
				title="Bucket not found"
				description="It may have been deleted, or it belongs to another team."
			>
				<template #action>
					<Button label="Back to object storage" route="/object-storage" />
				</template>
			</EmptyState>

			<template v-else>
				<div
					class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between"
				>
					<div class="min-w-0 flex-1 space-y-1.5">
						<h1 class="truncate text-2xl-semibold text-ink-gray-9">
							{{ bucketLabel(bucket) }}
						</h1>
						<p class="truncate text-base text-ink-gray-5">{{ summary }}</p>
					</div>
					<Button
						icon-right="lucide-copy"
						:aria-label="`Copy endpoint ${bucket.endpoint_url}`"
						:title="bucket.endpoint_url"
						class="max-w-full shrink-0 font-mono md:max-w-sm"
						@click="copyEndpoint(bucket.endpoint_url)"
					>
						<span class="truncate">{{ bucket.endpoint_url }}</span>
					</Button>
				</div>

				<Tabs v-model="activeTab" :tabs="tabs" class="mt-6">
					<template #tab-label="{ tab }">{{ tab.label }}</template>
					<template #tab-panel="{ tab }">
						<BucketFiles
							v-if="tab.value === 'files'"
							:bucket="bucket"
							:can-download="canManageServices"
							class="mt-6"
						/>
						<BucketSettings
							v-else
							:bucket="bucket"
							:can-manage="canManageServices"
							class="mt-6"
							@rotated="credentials = $event"
							@deleted="router.push('/object-storage')"
						/>
					</template>
				</Tabs>
			</template>
		</div>

		<CredentialsDialog v-model="credentials" />
	</div>
</template>
