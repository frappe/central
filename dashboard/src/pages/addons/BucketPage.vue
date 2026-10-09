<script setup lang="ts">
import { Button, TabButtons } from 'frappe-ui'
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

reload()

const bucket = computed(() =>
	buckets.value.find((item) => item.name === route.params.name),
)

watch(
	() => bucket.value?.name,
	(name) => {
		setBreadcrumbs([
			{ label: 'Object Storage', route: { path: '/object-storage' } },
			{ label: bucket.value ? bucketLabel(bucket.value) : 'Bucket' },
		])

		if (name) loadUsage(name)
	},
	{ immediate: true },
)

const facts = computed(() => {
	const current = bucket.value
	if (!current) return []

	const region = regions.value.find((r) => r.region === current.region)

	return [
		{
			icon: 'lucide-map-pin',
			label: region ? regionLabel(region) : current.region,
		},
		...(usage.value
			? [
					{
						icon: 'lucide-hard-drive',
						label: formatBytes(usage.value.used_bytes),
					},
					{
						icon: 'lucide-files',
						label: `${usage.value.object_count.toLocaleString()} objects`,
					},
				]
			: []),
	]
})

const tabs = [
	{ label: 'Files', value: 'files', iconLeft: 'lucide-folder' },
	{ label: 'Settings', value: 'settings', iconLeft: 'lucide-settings' },
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
	<div class="flex h-full flex-col">
		<div
			class="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col p-3 md:p-4 lg:pt-8"
		>
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
					<Button label="Back to Object Storage" route="/object-storage" />
				</template>
			</EmptyState>

			<template v-else>
				<header
					class="flex flex-col gap-4 rounded-6 border border-outline-gray-2 p-4 md:flex-row md:items-center md:justify-between"
				>
					<div class="flex min-w-0 items-center gap-3">
						<span
							class="grid size-10 shrink-0 place-items-center rounded-4 bg-surface-gray-2 text-ink-gray-6"
						>
							<span class="lucide-archive size-5" />
						</span>

						<div class="min-w-0 space-y-1.5">
							<h1 class="truncate text-xl-semibold text-ink-gray-9">
								{{ bucketLabel(bucket) }}
							</h1>

							<ul class="flex flex-wrap items-center gap-x-4 gap-y-1">
								<li
									v-for="fact in facts"
									:key="fact.icon"
									class="flex items-center gap-1.5 text-sm text-ink-gray-5"
								>
									<span :class="fact.icon" class="size-3.5 shrink-0" />
									{{ fact.label }}
								</li>
							</ul>
						</div>
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
				</header>

				<TabButtons
					v-model="activeTab"
					:options="tabs"
					class="mt-6 self-start"
				/>

				<BucketFiles
					v-if="activeTab === 'files'"
					:bucket="bucket"
					:can-download="canManageServices"
					class="mt-4 min-h-0 flex-1"
				/>

				<BucketSettings
					v-else
					:bucket="bucket"
					:can-manage="canManageServices"
					class="mt-6 min-h-0 overflow-y-auto"
					@rotated="credentials = $event"
					@deleted="router.push('/object-storage')"
				/>
			</template>
		</div>

		<CredentialsDialog v-model="credentials" />
	</div>
</template>
