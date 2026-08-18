<script setup lang="ts">
import { LoadingText, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import type { TaxSummary } from '@/types/billing'

// Tax charged over the window, grouped by the mechanic that applied it (GST,
// zero-rated, withheld). Useful for reconciling; explicitly NOT the filing
// document, which ERPNext issues (ADR 0019) — the footer says so, because a page
// headed "tax" that stays quiet about that invites exactly the wrong assumption.
const { activeTeam } = useSession()

const tax = useCall<TaxSummary, { team: string }>({
	url: method(API.taxSummary),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => tax.reload())

const loading = computed(() => tax.loading && !tax.data)
const data = computed(() => tax.data)
const currency = computed(() => data.value?.currency ?? 'INR')
const hasTax = computed(
	() =>
		(data.value?.total_tax ?? 0) > 0 || (data.value?.total_withheld ?? 0) > 0,
)
</script>

<template>
	<BillingCard title="Tax">
		<LoadingText v-if="loading" :lines="3" />

		<template v-else-if="data">
			<div v-if="hasTax">
				<ul class="divide-y divide-outline-gray-1">
					<li
						v-for="bucket in data.by_type"
						:key="bucket.tax_type"
						class="flex items-baseline justify-between gap-3 py-2.5 first:pt-0"
					>
						<div class="min-w-0">
							<span class="text-p-sm text-ink-gray-8"
								>{{ bucket.tax_type }}</span
							>
							<span class="ml-1.5 text-p-sm text-ink-gray-4">
								on {{ money(bucket.taxable, currency) }}
							</span>
						</div>
						<span class="shrink-0 text-p-sm tabular-nums text-ink-gray-9">
							{{ money(bucket.tax, currency) }}
						</span>
					</li>
				</ul>
				<div
					v-if="data.total_withheld > 0"
					class="mt-2 flex items-baseline justify-between gap-3 border-t border-outline-gray-1 pt-2.5"
				>
					<span class="text-p-sm text-ink-gray-8"
						>Withheld at source (TDS)</span
					>
					<span class="text-p-sm tabular-nums text-ink-gray-9">
						{{ money(data.total_withheld, currency) }}
					</span>
				</div>
			</div>

			<p v-else class="py-2 text-p-sm text-ink-gray-5">
				No tax was charged on your invoices in this period.
			</p>

			<p class="mt-3 text-p-sm text-ink-gray-5">
				Figures as we rated them, for checking against your own records.
			</p>
		</template>
	</BillingCard>
</template>
