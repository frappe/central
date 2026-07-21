<script setup lang="ts">
import { Select } from 'frappe-ui'
import type { ServerVisual } from '@/lib/serverMap'

// The top-right status + region filters over the map. Both scope the map pins
// and the panel rows; the page owns the option lists and the resolved filters.
defineProps<{
	statusOptions: { label: string; value: string }[]
	statusDot: string
	regionOptions: { label: string; value: string }[]
}>()

const statusFilter = defineModel<ServerVisual['key'] | ''>('statusFilter', { required: true })
const regionSelection = defineModel<string>('regionSelection', { required: true })
</script>

<template>
	<div class="absolute right-4 top-4 flex items-center gap-2">
		<Select v-model="statusFilter" variant="outline" size="md" :options="statusOptions">
			<template #prefix>
				<span
					class="size-2 shrink-0 rounded-full transition-colors"
					:style="{ background: statusDot }"
				/>
			</template>
		</Select>
		<Select v-model="regionSelection" variant="outline" size="md" :options="regionOptions" />
	</div>
</template>
