<script setup lang="ts">
import { computed, ref } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { money } from '@/lib/format'
import type { SpendHistory } from '@/types/billing'

// Where the money went, over the same window — by product family, or by region.
// Two cuts of one number, so they share a card and a toggle rather than compete
// for two: a customer asks "on what" or "where", never both at once.
const props = defineProps<{ history: SpendHistory }>()
const axis = ref<'product' | 'region'>('product')

const rows = computed(() =>
	axis.value === 'product' ? props.history.by_product : props.history.by_region,
)
const total = computed(() => rows.value.reduce((sum, r) => sum + r.amount, 0))
function sharePct(amount: number): number {
	return total.value > 0 ? Math.round((amount / total.value) * 100) : 0
}
</script>

<template>
	<BillingCard title="Where it went">
		<template #action>
			<div class="flex overflow-hidden rounded-md border border-outline-gray-2">
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

		<div v-if="rows.length" class="space-y-3">
			<div v-for="row in rows" :key="row.label">
				<div class="flex items-baseline justify-between gap-3">
					<span class="min-w-0 truncate text-p-sm text-ink-gray-8">
						{{ row.label }}
					</span>
					<span class="shrink-0 text-p-sm tabular-nums text-ink-gray-6">
						{{ money(row.amount, history.currency) }}
						<span class="text-ink-gray-4">· {{ sharePct(row.amount) }}%</span>
					</span>
				</div>
				<div class="mt-1 h-1 overflow-hidden rounded-full bg-surface-gray-2">
					<span
						class="block h-full rounded-full bg-surface-gray-10"
						:style="{ width: `${sharePct(row.amount)}%` }"
					/>
				</div>
			</div>
		</div>
		<p v-else class="py-4 text-center text-p-sm text-ink-gray-5">
			No itemised charges in this period.
		</p>
	</BillingCard>
</template>
