<script setup lang="ts">
import { Button, Skeleton, TabButtons } from 'frappe-ui'

const pageSizeOptions = [10, 20, 50] as const

withDefaults(
	defineProps<{
		page: number
		pageCount: number
		pageSize: number
		canPrevious: boolean
		canNext: boolean
		paginated?: boolean
		showCount?: boolean
		countText?: string
		countLoading?: boolean
	}>(),
	{
		paginated: true,
		showCount: true,
		countText: '',
		countLoading: false,
	},
)

defineEmits<{
	first: []
	previous: []
	next: []
	last: []
	pageSizeChange: [pageSize: number]
}>()
</script>

<template>
	<footer class="flex flex-wrap items-center justify-between gap-2 pt-2">
		<div v-if="showCount" class="min-w-0 shrink-0">
			<Skeleton v-if="countLoading" class="h-3 w-16 rounded" />
			<p v-else class="truncate text-sm text-ink-gray-5 tabular-nums">
				{{ countText }}
			</p>
		</div>

		<div v-if="paginated" class="flex flex-wrap items-center gap-3 sm:ml-auto">
			<TabButtons
				:model-value="pageSize"
				:options="pageSizeOptions.map((value) => ({ label: String(value), value }))"
				@update:model-value="$emit('pageSizeChange', Number($event))"
			/>

			<span class="whitespace-nowrap text-sm text-ink-gray-5 tabular-nums">
				Page {{ page }} of {{ Math.max(pageCount, 1) }}
			</span>

			<div class="flex items-center">
				<Button
					icon="lucide-chevrons-left"
					variant="ghost"
					tooltip="First page"
					:disabled="!canPrevious"
					@click="$emit('first')"
				/>
				<Button
					icon="lucide-chevron-left"
					variant="ghost"
					tooltip="Previous page"
					:disabled="!canPrevious"
					@click="$emit('previous')"
				/>
				<Button
					icon="lucide-chevron-right"
					variant="ghost"
					tooltip="Next page"
					:disabled="!canNext"
					@click="$emit('next')"
				/>
				<Button
					icon="lucide-chevrons-right"
					variant="ghost"
					tooltip="Last page"
					:disabled="!canNext"
					@click="$emit('last')"
				/>
			</div>
		</div>
	</footer>
</template>
