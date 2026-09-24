<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { bucketLabel } from '@/composables/useObjectStorage'
import { timeAgo } from '@/lib/datetime'
import type { StorageBucket } from '@/types/storage'

interface Props {
	bucket: StorageBucket
	region: string
	active: boolean
}

defineProps<Props>()
defineEmits<{ select: [] }>()
</script>

<template>
	<button
		type="button"
		class="group flex w-full flex-col gap-5 rounded-6 border p-4 text-left transition-colors hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
		:class="
			active
				? 'border-outline-gray-4 bg-surface-gray-2'
				: 'border-outline-gray-2'
		"
		:aria-pressed="active"
		@click="$emit('select')"
	>
		<div class="flex w-full items-start gap-3">
			<span
				class="grid size-9 shrink-0 place-items-center rounded-4 bg-surface-gray-2 text-ink-gray-6 group-hover:bg-surface-gray-3"
				:class="{ 'bg-surface-gray-3': active }"
				aria-hidden="true"
			>
				<span
					:class="bucket.is_managed ? 'lucide-shield-check' : 'lucide-archive'"
					class="size-4"
				/>
			</span>

			<span class="min-w-0 flex-1 truncate text-base-semibold text-ink-gray-9">
				{{ bucketLabel(bucket) }}
				<span class="mt-1 block truncate font-mono text-xs text-ink-gray-5">
					{{ bucket.bucket_name }}
				</span>
			</span>

			<Badge
				v-if="bucket.status !== 'Active'"
				theme="amber"
				:label="bucket.status"
			/>
		</div>

		<span
			class="flex w-full items-center justify-between gap-3 text-sm text-ink-gray-5"
		>
			<span class="flex min-w-0 items-center gap-1.5">
				<span class="lucide-map-pin size-3.5 shrink-0" aria-hidden="true" />
				{{ region }}
			</span>
			<span class="shrink-0">{{ timeAgo(bucket.creation) }}</span>
		</span>
	</button>
</template>
