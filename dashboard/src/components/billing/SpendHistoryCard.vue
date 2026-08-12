<script setup lang="ts">
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { money } from '@/lib/format'
import type { SpendHistory } from '@/types/billing'

// Month-by-month spend. A tray is scoped to one cycle; this is the thing that
// genuinely isn't — so it lives here rather than behind a card on Overview.
//
// Every month in the window is drawn, including the empty ones: a gap in a spend
// chart should read as a month with no spend, not as missing data.
const props = defineProps<{ history: SpendHistory }>()

const months = computed(() => props.history.months)
const peak = computed(() =>
	Math.max(1, ...months.value.map((m) => m.total)),
)
const average = computed(() => {
	const billed = months.value.filter((m) => m.total > 0)
	if (!billed.length) return 0
	return billed.reduce((sum, m) => sum + m.total, 0) / billed.length
})
function heightPct(total: number): number {
	return total > 0 ? Math.max(3, Math.round((total / peak.value) * 100)) : 0
}
</script>

<template>
	<BillingCard
		title="Month by month"
		:description="`${money(history.total, history.currency)} across ${history.invoice_count} invoice${history.invoice_count === 1 ? '' : 's'} · ${money(average, history.currency)} average`"
	>
		<div class="flex h-40 items-end gap-1.5">
			<div
				v-for="m in months"
				:key="m.month"
				class="group flex h-full flex-1 flex-col justify-end"
				:title="`${m.label} — ${money(m.total, history.currency)}`"
			>
				<div
					class="w-full rounded-t transition-colors"
					:class="m.total > 0 ? 'bg-surface-blue-5 group-hover:bg-surface-blue-6' : 'bg-surface-gray-2'"
					:style="{ height: m.total > 0 ? `${heightPct(m.total)}%` : '2px' }"
				/>
			</div>
		</div>
		<div class="mt-2 flex gap-1.5">
			<span
				v-for="m in months"
				:key="m.month"
				class="flex-1 truncate text-center text-xs text-ink-gray-4"
			>
				{{ m.label }}
			</span>
		</div>
	</BillingCard>
</template>
