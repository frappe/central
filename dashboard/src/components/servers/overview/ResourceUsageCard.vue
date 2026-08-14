<script setup lang="ts">
import { computed } from 'vue'
import UsageMeter from '@/components/servers/overview/UsageMeter.vue'
import { formatBytes, usagePercent } from '@/lib/bytes'

const props = defineProps<{
	available: boolean
	vcpus?: number | null
	cpuPercent?: number | null
	memoryUsed?: number | null
	memoryTotal?: number | null
	diskUsed?: number | null
	diskTotal?: number | null
	canExpandStorage?: boolean
}>()

defineEmits<{ expandStorage: [] }>()

const cpuLabel = computed(() => {
	const used = props.cpuPercent
	const cores = props.vcpus
	if (used == null) return `— of ${cores ?? '—'} vCPU`
	return `${used.toFixed(0)}% of ${cores ?? '—'} vCPU`
})
</script>

<template>
	<section class="rounded-7 border border-outline-gray-2 p-5">
		<div class="mb-5 flex items-center justify-between gap-3">
			<h3 class="text-base font-semibold text-ink-gray-9">Resource usage</h3>
			<span class="flex items-center gap-1.5 text-sm text-ink-gray-5">
				<span class="size-1.5 rounded-full bg-surface-green-7" aria-hidden="true" />
				Last 24 hours
			</span>
		</div>

		<div v-if="available" class="space-y-5">
			<UsageMeter
				label="CPU"
				:value="cpuLabel"
				:percent="Math.min(100, Math.max(0, cpuPercent ?? 0))"
			/>
			<UsageMeter
				label="Memory"
				:value="`${formatBytes(memoryUsed)} of ${formatBytes(memoryTotal)}`"
				:percent="usagePercent(memoryUsed, memoryTotal)"
			/>
			<UsageMeter
				label="Storage"
				:value="`${formatBytes(diskUsed)} of ${formatBytes(diskTotal)}`"
				:percent="usagePercent(diskUsed, diskTotal)"
				:action-label="canExpandStorage ? 'Expand storage' : undefined"
				@action="$emit('expandStorage')"
			/>
		</div>
		<p v-else class="text-p-sm text-ink-gray-5">
			Live metrics are unavailable for this server right now.
		</p>
	</section>
</template>
