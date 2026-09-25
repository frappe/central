<script setup lang="ts">
import { computed } from 'vue'
import { useMeteredServices } from '@/composables/useMeteredServices'
import { bucketLabel, useObjectStorage } from '@/composables/useObjectStorage'
import { formatBytes } from '@/lib/bytes'
import { money, plural } from '@/lib/format'

const COLORS = [
	'bg-surface-blue-7',
	'bg-surface-pink-7',
	'bg-surface-violet-7',
	'bg-surface-orange-7',
	'bg-surface-cyan-7',
]

const { buckets, usages } = useObjectStorage()
const { availablePlans, currency } = useMeteredServices()

const totalBytes = computed(() =>
	buckets.value.reduce(
		(sum, bucket) => sum + (usages.value[bucket.name]?.used_bytes ?? 0),
		0,
	),
)

const segments = computed(() => {
	const bySize = buckets.value
		.map((bucket) => ({
			bucket,
			bytes: usages.value[bucket.name]?.used_bytes ?? 0,
		}))
		.sort((a, b) => b.bytes - a.bytes)
	const otherBytes = bySize
		.slice(COLORS.length)
		.reduce((sum, { bytes }) => sum + bytes, 0)

	const named = bySize
		.slice(0, COLORS.length)
		.map(({ bucket, bytes }, index) => ({
			label: bucketLabel(bucket),
			bytes,
			color: COLORS[index],
		}))
	const all = otherBytes
		? [
				...named,
				{ label: 'Other', bytes: otherBytes, color: 'bg-surface-gray-5' },
			]
		: named

	return all.map((segment) => ({
		...segment,
		size: formatBytes(segment.bytes),
		percent: (segment.bytes / capacityBytes.value) * 100,
	}))
})

const objects = computed(() =>
	buckets.value
		.reduce(
			(sum, bucket) => sum + (usages.value[bucket.name]?.object_count ?? 0),
			0,
		)
		.toLocaleString(),
)

const regions = computed(
	() => new Set(buckets.value.map((bucket) => bucket.region)).size,
)

const plan = computed(() =>
	availablePlans.value.find((plan) => plan.resource_type === 'Storage'),
)

const includedBytes = computed(
	() => (plan.value?.allowance ?? 0) * 1024 ** 3 * regions.value,
)

const capacityBytes = computed(
	() => Math.max(includedBytes.value, totalBytes.value) || 1,
)

const monthlyCost = computed(() =>
	plan.value
		? money(plan.value.rate * regions.value, currency.value, {
				trimTrailingZeros: true,
			})
		: '—',
)
</script>

<template>
	<section class="space-y-4 border rounded-4 p-4 border-outline-gray-2">
		<p
			class="flex flex-wrap items-baseline justify-between gap-3 text-sm text-ink-gray-5"
		>
			<span>
				<span class="text-2xl-semibold tabular-nums text-ink-gray-9">
					{{ formatBytes(totalBytes) }}
				</span>
				<template v-if="includedBytes">
					of {{ formatBytes(includedBytes) }} included
				</template>
				· {{ objects }} objects · {{ plural(regions, 'region') }}
			</span>
			<span>
				<span class="text-base-semibold tabular-nums text-ink-gray-9">
					{{ monthlyCost }}
				</span>
				/ month
			</span>
		</p>

		<div
			class="flex h-2 gap-0.5 overflow-hidden rounded-full bg-surface-gray-2"
			role="img"
			:aria-label="
				segments.map((segment) => `${segment.label} ${segment.size}`).join(', ')
			"
		>
			<span
				v-for="segment in segments"
				v-show="segment.percent"
				:key="segment.label"
				:class="segment.color"
				:style="{ width: `${segment.percent}%` }"
				:title="`${segment.label} · ${segment.size}`"
			/>
		</div>

		<ul class="flex flex-wrap gap-x-4 gap-y-1.5 text-sm text-ink-gray-7">
			<li
				v-for="segment in segments"
				:key="segment.label"
				class="flex items-center gap-1.5 mr-1"
			>
				<span :class="segment.color" class="size-2 rounded-full" />
				{{ segment.label }}
				<span class="tabular-nums text-xs text-ink-gray-5 "
					>{{ segment.size }}</span
				>
			</li>
			<li
				v-if="includedBytes > totalBytes"
				class="flex items-center gap-1.5 mr-1"
			>
				<span class="size-2 rounded-full bg-surface-gray-4" />
				Free
				<span class="tabular-nums text-xs text-ink-gray-5">
					{{ formatBytes(includedBytes - totalBytes) }}
				</span>
			</li>
		</ul>
	</section>
</template>
