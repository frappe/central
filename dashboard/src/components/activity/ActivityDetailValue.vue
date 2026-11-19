<script setup lang="ts">
import { formatDetailValue } from '@/lib/activity'
import type { ActivityDetail } from '@/types/activity'

interface Props {
	detail: ActivityDetail
}

defineProps<Props>()
</script>

<template>
	<span class="inline-flex min-w-0 flex-wrap items-center gap-x-1.5">
		<template v-if="detail.from && detail.to">
			<span class="text-ink-gray-5 line-through">
				{{ formatDetailValue(detail.label, detail.from) }}
			</span>
			<span class="text-ink-gray-4" aria-label="changed to">→</span>
			<span class="font-medium text-ink-gray-9">
				{{ formatDetailValue(detail.label, detail.to) }}
			</span>
		</template>
		<span v-else-if="detail.to" class="font-medium text-ink-gray-9">
			{{ formatDetailValue(detail.label, detail.to) }}
		</span>
		<span v-else-if="detail.from" class="text-ink-gray-5">
			{{ formatDetailValue(detail.label, detail.from) }}
		</span>
		<span v-else class="text-ink-gray-5">Updated</span>
	</span>
</template>
