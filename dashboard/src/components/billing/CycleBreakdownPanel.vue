<script setup lang="ts">
import { LoadingText } from 'frappe-ui'
import { computed } from 'vue'
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

// Owed first, then inferred: the reader should meet the facts before the
// estimates, and the totals below repeat that order.
const ordered = computed(() =>
	[...lines.value].sort(
		(a, b) => Number(isEstimated(a)) - Number(isEstimated(b)),
	),
)

function isEstimated(line: BillingLine): boolean {
	return line.basis === 'Estimated' || line.basis === 'Assumed'
}

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
			<ul class="divide-y divide-outline-gray-1">
				<li
					v-for="(line, idx) in ordered"
					:key="idx"
					class="flex items-start justify-between gap-3 px-4 py-3"
				>
					<div class="min-w-0">
						<div class="truncate text-base-medium text-ink-gray-9">
							{{ line.item }}
						</div>
						<div v-if="line.detail" class="mt-0.5 text-p-sm text-ink-gray-5">
							{{ line.detail }}
						</div>
					</div>
					<div class="flex shrink-0 items-center gap-2">
						<span class="text-sm-medium tabular-nums text-ink-gray-9">
							{{ money(line.amount, currency) }}
						</span>
						<!-- The tag is the whole reason this tray exists: it says which
						     numbers are facts and which are inference. -->
						<span
							class="rounded px-1.5 py-0.5 text-xs"
							:class="
                isEstimated(line)
                  ? 'bg-surface-gray-2 text-ink-gray-6'
                  : 'bg-surface-blue-2 text-ink-blue-3'
              "
						>
							{{ isEstimated(line) ? 'Est.' : 'Owed' }}
						</span>
					</div>
				</li>
			</ul>

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
