<script setup lang="ts">
import { LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import ChargeBreakdown from '@/components/billing/ChargeBreakdown.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { billingPeriod } from '@/lib/date'
import { money } from '@/lib/format'
import type { BillingLine } from '@/types/billing'

// The tray behind "This cycle": every line that makes up the projection, each
// tagged with whether it is already owed or still inferred, then the totals it
// sums to. The split is the point — a bill that is part guesswork must not read
// like a bill, so the card refuses to quote a bare number and this explains it.
const open = defineModel<boolean>('open', { default: false })
const { forecast, currency } = useBillingOverview()

const loading = computed(() => forecast.loading && !forecast.data)
const fc = computed(() => forecast.data)
const lines = computed<BillingLine[]>(() => fc.value?.line_items ?? [])



const period = computed(() =>
	fc.value ? billingPeriod(fc.value.period_start, fc.value.period_end) : '',
)
</script>

<template>
	<SidePanel
		v-model:open="open"
		title="This cycle"
		:subtitle="period"
	>
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>

		<div v-else-if="!lines.length" class="px-4 py-12 text-center text-p-sm text-ink-gray-5">
			Nothing is being billed this cycle yet.
		</div>

		<template v-else>
			<div class="p-4">
				<ChargeBreakdown :lines="lines" :currency="currency" show-basis />
			</div>

			<div class="border-t border-outline-gray-2 p-4">
				<div class="flex items-baseline justify-between gap-3 py-1">
					<span class="text-p-sm text-ink-gray-5">Already owed</span>
					<span class="text-sm-medium tabular-nums text-ink-gray-8">
						{{ money(fc?.measured ?? 0, currency) }}
					</span>
				</div>
				<div
					v-if="fc?.has_estimates"
					class="flex items-baseline justify-between gap-3 py-1"
				>
					<span class="text-p-sm text-ink-gray-5">Estimated remainder</span>
					<span class="text-sm-medium tabular-nums text-ink-gray-8">
						{{ money(fc?.estimated ?? 0, currency) }}
					</span>
				</div>
				<div
					v-if="fc?.tax_amount"
					class="flex items-baseline justify-between gap-3 py-1"
				>
					<span class="text-p-sm text-ink-gray-5">
						{{ fc?.tax_type || 'Tax' }}
					</span>
					<span class="text-sm-medium tabular-nums text-ink-gray-8">
						{{ money(fc?.tax_amount ?? 0, currency) }}
					</span>
				</div>
				<div
					class="mt-2 flex items-baseline justify-between gap-3 border-t border-outline-gray-1 pt-3"
				>
					<span class="text-base-medium text-ink-gray-9">Projected total</span>
					<span class="text-lg-semibold tabular-nums text-ink-gray-9">
						{{ money(fc?.projected_total ?? 0, currency) }}
					</span>
				</div>

				<p v-if="fc?.has_estimates" class="mt-3 text-p-sm text-ink-gray-5">
					Estimated lines are metered services nobody has finished using this
					month. They're inferred from your own usage so far — everything else is
					already fixed.
				</p>
			</div>
		</template>
	</SidePanel>
</template>
