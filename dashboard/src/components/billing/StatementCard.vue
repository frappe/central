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
const VISIBLE = 5
defineProps<{ exportUrl: string }>()
defineEmits<{ open: [] }>()
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

const owed = computed(() => Number(data.value?.closing_outstanding ?? 0) > 0)
const rows = computed(() => (data.value?.rows ?? []).slice(-VISIBLE).reverse())
const hidden = computed(() => Math.max(0, (data.value?.rows?.length ?? 0) - VISIBLE))

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

			<!-- The four figures above are the working; this is the answer, so it gets
			     a block of its own rather than another row in the same rhythm. Red type
			     alone was carrying the emphasis and it read as list, not conclusion. -->
			<div
				class="mt-4 flex items-center justify-between gap-3 rounded-md border px-3.5 py-3"
				:class="
          owed
            ? 'border-outline-red-3 bg-surface-red-1'
            : 'border-outline-gray-2 bg-surface-gray-1'
        "
			>
				<span class="flex items-center gap-2">
					<span
						v-if="owed"
						class="lucide-alert-circle size-4 shrink-0 text-ink-red-7"
						aria-hidden="true"
					/>
					<span
						v-else
						class="lucide-check-circle-2 size-4 shrink-0 text-ink-green-8"
						aria-hidden="true"
					/>
					<span class="text-base-medium text-ink-gray-8">
						{{ owed ? 'Still outstanding' : 'Nothing outstanding' }}
					</span>
				</span>
				<span
					class="text-lg-semibold tabular-nums"
					:class="owed ? 'text-ink-red-7' : 'text-ink-gray-9'"
				>
					{{ money(data.closing_outstanding, currency) }}
				</span>
			</div>

			<ul
				v-if="rows.length"
				class="mt-4 divide-y divide-outline-gray-1 border-t border-outline-gray-1"
			>
				<li
					v-for="row in rows"
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

			<Button
				v-if="hidden"
				variant="ghost"
				size="sm"
				class="-ml-2 mt-2"
				:label="`View all ${data.rows.length}`"
				@click="$emit('open')"
			>
				<template #suffix>
					<span class="lucide-chevron-right size-4" aria-hidden="true" />
				</template>
			</Button>

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
