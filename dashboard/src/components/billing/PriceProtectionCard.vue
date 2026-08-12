<script setup lang="ts">
import { computed } from 'vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { money } from '@/lib/format'

// Your prices are locked — grandfathering, made visible to the customer it
// protects. A rate is struck when the segment opens and never re-read (ADR 0010),
// so a catalog increase leaves the customer where they were. Nobody knew.
//
// The card renders only when there is something true to say: either a rate held
// below today's list, or one now sitting above it. A team on exactly list price
// gets nothing, because "you are paying list price" is not news.
defineEmits<{ open: [] }>()
const { lockedPrices, currency } = useBillingOverview()

const data = computed(() => lockedPrices.data)
const saving = computed(() => Number(data.value?.monthly_saving ?? 0))
const protectedCount = computed(() => Number(data.value?.protected_count ?? 0))
const aboveList = computed(() => Number(data.value?.above_list_count ?? 0))
const total = computed(() => data.value?.rows?.length ?? 0)

const show = computed(() => protectedCount.value > 0 || aboveList.value > 0)
</script>

<template>
	<button
		v-if="show"
		type="button"
		class="flex w-full items-center justify-between gap-4 rounded-lg border border-outline-gray-2 bg-surface-base p-5 text-left transition-colors hover:border-outline-gray-3"
		@click="$emit('open')"
	>
		<div class="min-w-0">
			<h2 class="text-base-semibold text-ink-gray-8">
				{{ protectedCount ? 'Your prices are locked' : 'Your locked prices' }}
			</h2>
			<p class="mt-0.5 text-p-sm text-ink-gray-5">
				<template v-if="protectedCount">
					{{ protectedCount }} of {{ total }} held below today's list price
				</template>
				<template v-else>
					{{ aboveList }} rate{{ aboveList === 1 ? '' : 's' }} now sit above
					today's list price
				</template>
			</p>
		</div>
		<div class="shrink-0 text-right">
			<p
				v-if="protectedCount"
				class="text-lg-semibold tabular-nums text-ink-green-3"
			>
				{{ money(saving, currency) }}<span
					class="text-p-sm font-normal text-ink-gray-5"
					>/mo</span
				>
			</p>
			<span
				class="lucide-chevron-right mt-1 inline-block size-4 text-ink-gray-4"
				aria-hidden="true"
			/>
		</div>
	</button>
</template>
