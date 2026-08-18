<script setup lang="ts">
defineProps<{
	label: string
	value: string
	percent: number
	/** Optional trailing control next to the label (e.g. expand storage). */
	actionLabel?: string
}>()

defineEmits<{ action: [] }>()
</script>

<template>
	<div>
		<div class="mb-2 flex items-center justify-between gap-4 text-sm">
			<span class="flex items-center gap-1.5 text-ink-gray-6">
				{{ label }}
				<button
					v-if="actionLabel"
					type="button"
					class="grid size-4 place-items-center rounded-4 text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8"
					:aria-label="actionLabel"
					@click="$emit('action')"
				>
					<span class="lucide-plus size-3" aria-hidden="true" />
				</button>
			</span>
			<span class="font-medium tabular-nums text-ink-gray-9">{{ value }}</span>
		</div>
		<div class="h-1 overflow-hidden rounded-full bg-surface-gray-2">
			<div
				class="h-full rounded-full bg-surface-gray-10 transition-[width] duration-300"
				:style="{ width: `${percent}%` }"
			/>
		</div>
	</div>
</template>
