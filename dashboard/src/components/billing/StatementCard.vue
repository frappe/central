<script setup lang="ts">
import { Badge, Button, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { billingPeriod } from '@/lib/date'
import { money } from '@/lib/format'
import { invoiceTheme } from '@/lib/status'
import type { Statement } from '@/types/billing'

const VISIBLE = 5
const COLUMNS = 'grid grid-cols-[1fr_5rem_7rem] items-center gap-3'
const props = defineProps<{
	statement: Statement | null
	loading: boolean
	exportUrl: string
}>()
defineEmits<{ open: [] }>()

const currency = computed(() => props.statement?.currency ?? 'INR')
const rows = computed(() =>
	(props.statement?.rows ?? []).slice(-VISIBLE).reverse(),
)
const hidden = computed(() =>
	Math.max(0, (props.statement?.rows?.length ?? 0) - VISIBLE),
)
</script>

<template>
	<BillingCard
		title="Statement of account"
		:description="
      statement
        ? billingPeriod(statement.from_date, statement.to_date)
        : undefined
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

		<template v-else>
			<template v-if="statement">
				<div v-if="rows.length" role="table" class="w-full">
					<div
						role="row"
						:class="COLUMNS"
						class="pb-2 pt-3 text-xs uppercase tracking-wide text-ink-gray-4"
					>
						<span role="columnheader">Period</span>
						<span role="columnheader" class="text-right">Status</span>
						<span role="columnheader" class="text-right">Amount</span>
					</div>

					<div
						class="divide-y divide-outline-gray-1 border-t border-outline-gray-1"
					>
						<div
							v-for="row in rows"
							:key="row.invoice"
							role="row"
							:class="COLUMNS"
							class="py-2.5"
						>
							<span
								role="cell"
								class="truncate text-p-sm text-ink-gray-8"
								:title="billingPeriod(row.period_start, row.period_end)"
							>
								{{ billingPeriod(row.period_start, row.period_end) }}
							</span>
							<span role="cell" class="flex justify-end">
								<Badge
									:theme="invoiceTheme(row.status)"
									variant="subtle"
									:label="row.status"
								/>
							</span>
							<span
								role="cell"
								class="text-right text-p-sm tabular-nums text-ink-gray-9"
							>
								{{ money(row.total, currency) }}
							</span>
						</div>
					</div>
				</div>

				<p v-else class="py-2 text-p-sm text-ink-gray-5">
					No invoices in this period.
				</p>
			</template>

			<p v-else class="py-2 text-p-sm text-ink-gray-5">
				Couldn't load the statement.
			</p>

			<div class="mt-2 flex flex-wrap items-center justify-between gap-2">
				<div class="-ml-2 flex items-center gap-1">
					<Button
						v-if="statement && hidden"
						variant="ghost"
						size="sm"
						:label="`View all ${statement.rows.length}`"
						@click="$emit('open')"
					>
						<template #suffix>
							<span class="lucide-chevron-right size-4" aria-hidden="true" />
						</template>
					</Button>
				</div>
				<p class="ml-auto text-p-sm text-ink-gray-5">
					For reconciling against your own records. Tax invoices are issued
					separately.
				</p>
			</div>
		</template>
	</BillingCard>
</template>
