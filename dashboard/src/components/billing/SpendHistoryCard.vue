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
const peak = computed(() => Math.max(1, ...months.value.map((m) => m.total)))
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
		<!-- Bars are monochrome on purpose: the dashboard fills meters with
		     ink-gray-8 on surface-gray-2 (UsageMeter, and frappe-ui's own Progress),
		     and reserves blue for interactive accents. A month with no spend gets a
		     baseline rule rather than a stub bar, which read as a rendering fault. -->
		<div class="flex h-36 items-end gap-2">
			<div
				v-for="m in months"
				:key="m.month"
				class="group flex h-full flex-1 flex-col justify-end"
				:title="`${m.label}: ${money(m.total, history.currency)}`"
			>
				<div
					v-if="m.total > 0"
					class="mx-auto w-full max-w-8 rounded-t-1 bg-surface-gray-10 transition-opacity group-hover:opacity-80"
					:style="{ height: `${heightPct(m.total)}%` }"
				/>
				<div v-else class="mx-auto h-px w-full max-w-8 bg-surface-gray-3" />
			</div>
		</div>
		<div class="mt-2 flex gap-2 border-t border-outline-gray-1 pt-2">
			<span
				v-for="m in months"
				:key="m.month"
				class="flex-1 truncate text-center text-p-sm text-ink-gray-5"
			>
				{{ m.label }}
			</span>
		</div>
	</BillingCard>
</template>
