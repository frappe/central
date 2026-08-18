<script setup lang="ts">
import { computed, ref } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { money } from '@/lib/format'
import type { SpendHistory, SpendSlice } from '@/types/billing'

// Where the money went — by product family, or by region. Two cuts of one number,
// so they share a card and a toggle: a customer asks "on what" or "where", never
// both at once.
//
// This is part-to-whole, so it is ONE stacked bar, not a bar per row. Three
// full-width rules under three labels read as heavy underlines rather than a
// comparison, and a near-black fill at that width is the "thick saturated block"
// every chart guide warns about. The bar carries the composition; the list below
// is its legend, and the percentages do the precise work.
const props = defineProps<{ history: SpendHistory }>()
const axis = ref<'product' | 'region'>('product')

// A sequential ramp, darkest = largest. Beyond four named slices the tail folds
// into "Other" rather than inventing a fifth tone nobody can tell apart.
// Stepped down from the near-black end of the ramp on purpose: at full width a
// #171717 band is a slab, not a chart. gray-9 still reads as clearly the darkest
// step while leaving the card calm.
const TONES = [
	'bg-surface-gray-9',
	'bg-surface-gray-7',
	'bg-surface-gray-5',
	'bg-surface-gray-4',
]
const OTHER_TONE = 'bg-surface-gray-3'
const MAX_SLICES = 4

const source = computed<SpendSlice[]>(() =>
	axis.value === 'product' ? props.history.by_product : props.history.by_region,
)
const total = computed(() => source.value.reduce((sum, r) => sum + r.amount, 0))

const slices = computed(() => {
	const rows = source.value
	const head = rows.slice(0, MAX_SLICES)
	const tail = rows.slice(MAX_SLICES)
	const out = head.map((row, i) => ({ ...row, tone: TONES[i] }))
	if (tail.length) {
		out.push({
			label: `Other (${tail.length})`,
			amount: tail.reduce((sum, r) => sum + r.amount, 0),
			tone: OTHER_TONE,
		})
	}
	return out
})

// A single slice is 100% of itself: the bar would be a full-width slab carrying
// no information the row beneath doesn't already state. Nothing to compose, so
// no composition bar.
const showBar = computed(() => slices.value.length > 1)

function sharePct(amount: number): number {
	return total.value > 0 ? Math.round((amount / total.value) * 100) : 0
}
// Floored so a 0.4% slice still shows as a sliver rather than vanishing.
function widthPct(amount: number): number {
	if (total.value <= 0) return 0
	return Math.max(1.5, (amount / total.value) * 100)
}
</script>

<template>
	<BillingCard title="Where it went">
		<template #action>
			<div class="flex overflow-hidden rounded-5 border border-outline-gray-2">
				<button
					v-for="opt in (['product', 'region'] as const)"
					:key="opt"
					type="button"
					class="border-r border-outline-gray-2 px-2.5 py-1 text-p-sm capitalize last:border-r-0 transition-colors"
					:class="
            axis === opt
              ? 'bg-surface-gray-2 text-ink-gray-9'
              : 'text-ink-gray-6 hover:bg-surface-gray-1'
          "
					@click="axis = opt"
				>
					{{ opt }}
				</button>
			</div>
		</template>

		<template v-if="slices.length">
			<!-- One composition bar. The gap between segments is surface, not a
			     border, so the divisions read at any width. -->
			<div
				v-if="showBar"
				class="mt-1 flex h-1.5 w-full gap-0.5 overflow-hidden"
				aria-hidden="true"
			>
				<span
					v-for="slice in slices"
					:key="slice.label"
					class="h-full rounded-1 first:rounded-l-full last:rounded-r-full"
					:class="slice.tone"
					:style="{ width: `${widthPct(slice.amount)}%` }"
				/>
			</div>

			<ul class="space-y-2.5" :class="showBar ? 'mt-4' : 'mt-1'">
				<li
					v-for="slice in slices"
					:key="slice.label"
					class="flex items-baseline justify-between gap-3"
				>
					<span class="flex min-w-0 items-baseline gap-2">
						<span
							class="size-2 shrink-0 translate-y-px rounded-1"
							:class="slice.tone"
							aria-hidden="true"
						/>
						<span class="truncate text-p-sm text-ink-gray-8"
							>{{ slice.label }}</span
						>
					</span>
					<span class="shrink-0 text-p-sm tabular-nums text-ink-gray-6">
						{{ money(slice.amount, history.currency) }}
						<span class="text-ink-gray-4">· {{ sharePct(slice.amount) }}%</span>
					</span>
				</li>
			</ul>
		</template>

		<p v-else class="py-4 text-center text-p-sm text-ink-gray-5">
			No itemised charges in this period.
		</p>
	</BillingCard>
</template>
