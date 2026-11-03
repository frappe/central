<script setup lang="ts">
import type { SummaryPart } from '@/lib/activity'

/** Changes on one line: labels stay quiet so the values stand out. */
interface Props {
	parts: SummaryPart[]
}

defineProps<Props>()
</script>

<template>
	<span class="inline-flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
		<template v-for="(part, index) in parts" :key="index">
			<span v-if="index" class="text-ink-gray-4" aria-hidden="true">·</span>
			<span class="inline-flex items-baseline gap-1">
				<span v-if="part.label" class="text-ink-gray-5">{{ part.label }}</span>
				<span v-if="part.value" class="text-ink-gray-7">{{ part.value }}</span>
			</span>
		</template>
	</span>
</template>
