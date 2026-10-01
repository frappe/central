<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import BucketCard from '@/components/addons/storage/BucketCard.vue'
import CreateBucketDialog from '@/components/addons/storage/CreateBucketDialog.vue'
import CredentialsDialog from '@/components/addons/storage/CredentialsDialog.vue'
import StorageSummary from '@/components/addons/storage/StorageSummary.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { useObjectStorage } from '@/composables/useObjectStorage'
import { getErrorMessage } from '@/lib/feedback'
import { regionLabel } from '@/lib/serverMap'
import type { BucketCredentials } from '@/types/storage'

const { setBreadcrumbs } = useBreadcrumbs()
setBreadcrumbs([{ label: 'Object storage' }])

const { canManageServices } = useCapabilities()
const { regions, buckets, loading, error, reload } = useObjectStorage()

const createOpen = ref(false)
const credentials = ref<BucketCredentials | null>(null)

const regionName = (code: string): string => {
	const region = regions.value.find((r) => r.region === code)
	return region ? regionLabel(region) : code
}

const canCreate = computed(
	() => canManageServices.value && regions.value.length > 0,
)
</script>

<template>
	<div class="h-full overflow-y-auto">
		<Teleport defer to="#header-actions">
			<Button
				v-if="canCreate && buckets.length"
				variant="solid"
				icon-left="lucide-plus"
				label="Create bucket"
				@click="createOpen = true"
			/>
		</Teleport>

		<div class="mx-auto w-full max-w-5xl p-3 md:p-4">
			<div v-if="loading" class="grid gap-3 md:grid-cols-2" aria-busy="true">
				<div
					v-for="index in 4"
					:key="index"
					class="h-32 animate-pulse rounded-6 bg-surface-gray-2"
				/>
			</div>

			<EmptyState
				v-else-if="error && !buckets.length"
				icon="lucide-cloud-off"
				title="Buckets couldn't load"
				:description="getErrorMessage(error, 'Try again in a moment.')"
			>
				<template #action>
					<Button label="Retry" @click="reload" />
				</template>
			</EmptyState>

			<EmptyState
				v-else-if="!buckets.length"
				icon="lucide-archive"
				:title="regions.length ? 'No buckets yet' : 'Not available yet'"
				:description="
					regions.length
						? 'Create a bucket in a region near your servers. You get an S3 endpoint and a key that opens only that bucket.'
						: 'Object storage is not available in any region yet.'
				"
			>
				<template v-if="canCreate" #action>
					<Button
						variant="solid"
						icon-left="lucide-plus"
						label="Create bucket"
						@click="createOpen = true"
					/>
				</template>
			</EmptyState>

			<template v-else>
				<StorageSummary />

				<div class="mt-4 grid gap-4 md:grid-cols-2">
					<BucketCard
						v-for="bucket in buckets"
						:key="bucket.name"
						:bucket="bucket"
						:region="regionName(bucket.region)"
					/>
				</div>
			</template>
		</div>

		<CreateBucketDialog v-model="createOpen" @created="credentials = $event" />
		<CredentialsDialog v-model="credentials" />
	</div>
</template>
