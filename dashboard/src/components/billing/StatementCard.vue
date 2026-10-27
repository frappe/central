<script setup lang="ts">
import { Badge, Button, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import Table from '@/components/common/Table.vue'
import { billingPeriod } from '@/lib/date'
import { money } from '@/lib/format'
import { invoiceTheme } from '@/lib/status'
import type { Statement } from '@/types/billing'

const props = defineProps<{
	statement: Statement | null
	loading: boolean
	exportUrl: string
}>()

const currency = computed(() => props.statement?.currency ?? 'INR')
const period = computed(() =>
	props.statement
		? billingPeriod(props.statement.from_date, props.statement.to_date)
		: undefined,
)
const rows = computed(() => [...(props.statement?.rows ?? [])].reverse())

const columns = [
	{ key: 'period', label: 'Period' },
	{ key: 'paid', label: 'Paid' },
	{ key: 'status', label: 'Status' },
	{ key: 'amount', label: 'Amount' },
]

const tableRows = computed(() =>
	rows.value.map((row) => ({
		id: row.invoice,
		period: billingPeriod(row.period_start, row.period_end),
		paid: money(row.amount_paid + row.credit_applied, currency.value),
		status: row.status,
		amount: money(row.total, currency.value),
	})),
)
</script>

<template>
	<BillingCard
		title="Statement"
		:description="period"
		title-info="For reconciling against your own records. Tax invoices are issued separately."
		flat
	>
		<template v-if="statement?.rows?.length" #action>
			<Button icon="lucide-download" label="Export CSV" :href="exportUrl" />
		</template>

		<LoadingText v-if="loading" :lines="3" />

		<p v-else-if="!statement" class="py-4 text-p-sm text-ink-gray-5">
			Couldn't load the statement.
		</p>

		<p v-else-if="!rows.length" class="py-4 text-p-sm text-ink-gray-5">
			No invoices in this period.
		</p>

		<Table v-else :columns="columns" :rows="tableRows">
			<template #period="{ row }">
				{{ row.period }}
			</template>

			<template #paid="{ row }">
				<span class="text-sm tabular-nums text-ink-gray-5">{{ row.paid }}</span>
			</template>

			<template #status="{ row }">
				<Badge :theme="invoiceTheme(row.status)" :label="row.status" />
			</template>

			<template #amount="{ row }">
				<span class="tabular-nums text-ink-gray-9">{{ row.amount }}</span>
			</template>
		</Table>
	</BillingCard>
</template>
