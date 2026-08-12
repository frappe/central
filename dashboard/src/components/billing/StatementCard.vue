<script setup lang="ts">
import { Badge, Button, LoadingText, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { billingPeriod } from '@/lib/date'
import { money } from '@/lib/format'
import type { Statement } from '@/types/billing'

// Statement of account — opening, charged, settled, closing. The shape someone
// hands an accountant, which is why the export sits on this card rather than only
// in the page header.
//
// This is NOT a tax invoice: the statutory document is issued by ERPNext (ADR
// 0019) and the sync is one-way, so we don't have it to give. The card says what
// it is rather than implying otherwise.
defineProps<{ exportUrl: string }>()
const { activeTeam } = useSession()

const statement = useCall<Statement, { team: string }>({
	url: method(API.statement),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => statement.reload())

const loading = computed(() => statement.loading && !statement.data)
const data = computed(() => statement.data)
const currency = computed(() => data.value?.currency ?? 'INR')

const summary = computed(() => {
	const d = data.value
	if (!d) return []
	return [
		{ label: 'Owed at start', value: d.opening_outstanding },
		{ label: 'Charged', value: d.charged },
		{ label: 'Paid by credits', value: d.settled_by_credits },
		{ label: 'Paid by card', value: d.settled_by_payment },
	]
})

const STATUS_THEME: Record<string, string> = {
	Paid: 'green',
	Open: 'blue',
	Overdue: 'red',
	Draft: 'gray',
	Waived: 'gray',
}
</script>

<template>
	<BillingCard
		title="Statement of account"
		:description="
      data ? billingPeriod(data.from_date, data.to_date) : undefined
    "
	>
		<template #action>
			<Button variant="ghost" size="xs" :link="exportUrl" label="Export">
				<template #prefix>
					<span class="lucide-download size-3.5" aria-hidden="true" />
				</template>
			</Button>
		</template>

		<LoadingText v-if="loading" :lines="4" />

		<template v-else-if="data">
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
				<div v-for="cell in summary" :key="cell.label">
					<p class="text-p-sm text-ink-gray-5">{{ cell.label }}</p>
					<p class="mt-0.5 text-base-medium tabular-nums text-ink-gray-9">
						{{ money(cell.value, currency) }}
					</p>
				</div>
			</div>

			<div
				class="mt-4 flex items-baseline justify-between gap-3 border-t border-outline-gray-1 pt-3"
			>
				<span class="text-base-medium text-ink-gray-9">Still outstanding</span>
				<span
					class="text-base-medium tabular-nums"
					:class="data.closing_outstanding > 0 ? 'text-ink-red-7' : 'text-ink-gray-9'"
				>
					{{ money(data.closing_outstanding, currency) }}
				</span>
			</div>

			<ul
				v-if="data.rows.length"
				class="mt-3 divide-y divide-outline-gray-1 border-t border-outline-gray-1"
			>
				<li
					v-for="row in data.rows"
					:key="row.invoice"
					class="flex items-center justify-between gap-3 py-2.5"
				>
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="truncate text-p-sm text-ink-gray-8">
								{{ billingPeriod(row.period_start, row.period_end) }}
							</span>
							<Badge
								:theme="(STATUS_THEME[row.status] as any) || 'gray'"
								:label="row.status"
							/>
						</div>
					</div>
					<span class="shrink-0 text-p-sm tabular-nums text-ink-gray-9">
						{{ money(row.total, currency) }}
					</span>
				</li>
			</ul>

			<!-- Says what it is. The statutory tax invoice is issued by ERPNext
			     (ADR 0019) and we cannot hand it over yet, so this must not imply a
			     download that does not exist (#70). -->
			<p class="mt-3 text-p-sm text-ink-gray-5">
				A summary of your account, for reconciling against your own records. Your
				tax invoices are issued separately.
			</p>
		</template>
	</BillingCard>
</template>
