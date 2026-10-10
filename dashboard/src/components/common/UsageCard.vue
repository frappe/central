<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { computed } from 'vue'

interface Props {
	label: string
	icon: string
	used: string
	limit?: string | null
	percent?: number | null
	badge?: string | null
}

const props = defineProps<Props>()

const badgeLabel = computed(() =>
	props.badge === undefined ? `${props.percent}% used` : props.badge,
)

const theme = computed(() => {
	if ((props.percent ?? 0) >= 90) return 'red'
	if ((props.percent ?? 0) >= 75) return 'amber'

	return 'gray'
})
</script>

<template>
	<div class="space-y-4 rounded-6 bg-surface-gray-1 p-4">
		<div class="flex h-5 items-center justify-between gap-3">
			<span class="flex items-center gap-2 text-sm text-ink-gray-6">
				<span :class="icon" class="size-4 text-ink-gray-5" />

				{{ label }}
			</span>

			<Badge
				v-if="percent != null && badgeLabel"
				:label="badgeLabel"
				:theme="theme"
			/>
		</div>

		<p class="flex items-baseline gap-1.5">
			<span class="text-2xl-semibold tabular-nums text-ink-gray-9">
				{{ used }}
			</span>

			<span v-if="limit" class="text-sm text-ink-gray-5">of {{ limit }}</span>
		</p>

		<div
			v-if="percent != null"
			class="h-1.5 overflow-hidden rounded-full bg-surface-gray-3"
		>
			<div
				class="h-full rounded-full bg-surface-gray-9"
				:style="{ width: `${percent}%` }"
			/>
		</div>
	</div>
</template>
