<script setup lang="ts">
import { HoverCard } from 'frappe-ui'
import { computed } from 'vue'
import { timeAgo, timestampZones } from '@/lib/datetime'

interface Props {
	value: string
}

const props = defineProps<Props>()

const ago = computed(() => timeAgo(props.value))
const zones = computed(() => timestampZones(props.value))
</script>

<template>
	<HoverCard
		side="top"
		align="end"
		:offset="8"
		:arrow="true"
		:hover-delay="120"
		:leave-delay="80"
	>
		<template #trigger>
			<span>
				<slot>{{ ago }}</slot>
			</span>
		</template>
		<div v-if="zones" class="flex min-w-72 flex-col gap-2 px-3 py-2.5">
			<p class="text-xs font-medium text-ink-gray-8">{{ ago }}</p>
			<div
				class="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1.5"
			>
				<template v-for="row in [zones.utc, zones.local]" :key="row.zone">
					<span
						class="justify-self-start rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-2xs text-ink-gray-6"
					>
						{{ row.zone }}
					</span>
					<span class="text-xs text-ink-gray-7">{{ row.date }}</span>
					<span class="text-xs tabular-nums text-ink-gray-6"
						>{{ row.time }}</span
					>
				</template>
			</div>
		</div>
	</HoverCard>
</template>
