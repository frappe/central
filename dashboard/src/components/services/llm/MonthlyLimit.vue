<script setup lang="ts">
import { Tooltip } from 'frappe-ui'
import { computed } from 'vue'
import { useAI } from '@/composables/useAI'
import { usd } from '@/lib/format'
import { __ } from '@/lib/translate'

const { ai } = useAI()
const limitHelp = __(
	"Your keys' caps and this month's spend, out of what your plan allows a month. Usage is billed at the end of the month.",
)
const spend = computed(() => ai.value?.spend)

const limitPercent = computed(() => {
	const limit = spend.value?.spend_limit ?? 0
	return limit > 0
		? Math.min(((spend.value?.committed ?? 0) / limit) * 100, 100)
		: 0
})

const limitBarClass = computed(() =>
	limitPercent.value >= 100
		? 'bg-surface-red-5'
		: limitPercent.value >= 80
			? 'bg-surface-amber-7'
			: 'bg-surface-gray-7',
)
</script>

<template>
	<dl class="flex flex-col gap-2 text-base">
		<div class="flex items-center justify-between gap-3">
			<dt class="flex items-center gap-1.5 text-ink-gray-7">
				{{ __('Monthly limit') }}
				<Tooltip :text="limitHelp">
					<span
						class="lucide-info size-3.5 text-ink-gray-4"
						:aria-label="__('What the monthly limit is')"
					/>
				</Tooltip>
			</dt>
			<dd v-if="spend?.spend_limit" class="tabular-nums text-ink-gray-5">
				<span class="text-base-medium text-ink-gray-9">
					{{ usd(spend.committed) }}
				</span>
				/ {{ usd(spend.spend_limit) }}
			</dd>
			<dd v-else class="text-ink-gray-5">{{ __('Not on your plan') }}</dd>
		</div>
		<div
			v-if="spend?.spend_limit"
			class="h-1.5 overflow-hidden rounded-full bg-surface-gray-3"
			role="meter"
			:aria-valuenow="Math.round(limitPercent)"
			aria-valuemin="0"
			aria-valuemax="100"
			:aria-label="__('Share of the monthly limit taken')"
		>
			<div
				class="h-full rounded-full transition-[width] duration-300 ease-out"
				:class="limitBarClass"
				:style="{ width: `${limitPercent}%` }"
			/>
		</div>
	</dl>
</template>
