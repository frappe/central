<script setup lang="ts">
import { Alert, Progress } from 'frappe-ui'
import { computed } from 'vue'
import { configSpecs } from '@/lib/composed'
import { timeAgo } from '@/lib/datetime'
import { __ } from '@/lib/translate'
import type { ResizeProgress, ResizeProgressStep } from '@/types/servers'

interface ResizeProgressProps {
	progress: ResizeProgress
}

const props = defineProps<ResizeProgressProps>()

const target = computed(() => {
	const { vcpus, memory_megabytes, disk_gigabytes } = props.progress.target
	return configSpecs({
		vcpus,
		memory_gb: memory_megabytes / 1024,
		disk_gb: disk_gigabytes,
	})
})

const ICON: Record<ResizeProgressStep['state'], string> = {
	done: 'lucide-circle-check text-ink-green-6',
	current: 'lucide-loader-circle animate-spin text-ink-gray-9',
	pending: 'lucide-circle text-ink-gray-4',
}
const LABEL: Record<ResizeProgressStep['state'], string> = {
	done: 'text-ink-gray-7',
	current: 'font-medium text-ink-gray-9',
	pending: 'text-ink-gray-5',
}

const doneCount = computed(
	() => props.progress.steps.filter((step) => step.state === 'done').length,
)

const current = computed(() =>
	props.progress.steps.find((step) => step.state === 'current'),
)
</script>

<template>
	<Alert
		v-if="progress.error"
		theme="red"
		:title="
			current
				? __('Resize failed at step: {0}', [current.label])
				: __('Resize failed')
		"
		:description="progress.error"
	/>

	<section
		v-else
		role="status"
		aria-live="polite"
		class="space-y-4 rounded-4 border border-outline-gray-2 p-4"
	>
		<p
			class="flex flex-wrap items-center justify-between gap-3 text-sm text-ink-gray-5"
		>
			<span class="min-w-0 truncate">
				{{ __('Resizing to') }}
				<span class="font-medium text-ink-gray-8">{{ target }}</span>
			</span>
			<span class="shrink-0">
				{{ __('Started {0}', [timeAgo(progress.started_at)]) }}
			</span>
		</p>

		<Progress
			:value="(doneCount / progress.steps.length) * 100"
			:intervals="progress.steps.length"
			size="sm"
		/>

		<ol class="flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
			<li
				v-for="step in progress.steps"
				:key="step.key"
				class="flex items-center gap-1.5"
				:class="LABEL[step.state]"
				:aria-current="step.state === 'current' ? 'step' : undefined"
			>
				<span
					class="size-4 shrink-0"
					:class="ICON[step.state]"
					aria-hidden="true"
				/>
				{{ step.label }}
			</li>
		</ol>
	</section>
</template>
