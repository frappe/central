<script setup lang="ts">
import dayjs from 'dayjs'
import { Badge, Button, DateRangePicker } from 'frappe-ui'
import { computed, ref } from 'vue'
import {
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import { billingPeriod, shortDate } from '@/lib/date'
import { money } from '@/lib/format'
import { downloadInvoice } from '@/lib/invoicePdf'
import { invoiceTheme } from '@/lib/status'
import type { InvoiceSummary } from '@/types/billing'

// Presentational: emits the clicked row; the page owns selection and the detail
// panel. The date range pre-filters here since it isn't a column filter.
const props = defineProps<{
	invoices: InvoiceSummary[]
	loading: boolean
	activeName?: string | null
}>()

const emit = defineEmits<{
	rowClick: [invoice: InvoiceSummary]
}>()

const range = ref<string[]>([]) // [fromISO, toISO], empty = any date
const today = dayjs().format('YYYY-MM-DD')

// The ranges people actually reach for when hunting an invoice — nobody picks
// two exact dates. ISO strings, like `range` below: setRange takes a two-item
// tuple and re-parses it, so there's nothing to gain from passing Dayjs.
const isoDaysAgo = (count: number, unit: 'month' | 'year'): string =>
	dayjs().subtract(count, unit).format('YYYY-MM-DD')

const datePresets: { label: string; range: () => [string, string] }[] = [
	{ label: 'Last month', range: () => [isoDaysAgo(1, 'month'), today] },
	{ label: 'Last 6 months', range: () => [isoDaysAgo(6, 'month'), today] },
	{ label: 'Last year', range: () => [isoDaysAgo(1, 'year'), today] },
]

// An invoice is issued when its period closes, so period_end is the row's date.
const rows = computed(() => {
	const [from, to] = range.value || []
	if (!from || !to) return props.invoices
	return props.invoices.filter(
		(inv) => inv.period_end && inv.period_end >= from && inv.period_end <= to,
	)
})
// The range narrows rows before ListView sees them, so tell it when that's
// happening — an empty result then reads "no matches", not "no invoices".
const dateActive = computed(() => {
	const [from, to] = range.value || []
	return !!from && !!to
})

const isOverdue = (inv: InvoiceSummary): boolean =>
	String(inv.status).toLowerCase() === 'overdue'

const columns: ListViewColumn<InvoiceSummary>[] = [
	{
		key: 'invoice',
		label: 'Invoice',
		// Search matches the number and the period as shown ("May 2026"). Sorting
		// stays chronological; the name would sort alphabetically.
		value: (invoice) =>
			`${invoice.name} ${billingPeriod(invoice.period_start, invoice.period_end)}`,
		sortable: true,
		compare: (a, b) => (a.period_end || '').localeCompare(b.period_end || ''),
	},
	{
		key: 'status',
		label: 'Status',
		width: '7rem',
		sortable: true,
		align: 'end',
	},
	{
		key: 'total',
		label: 'Amount',
		width: '7rem',
		sortable: true,
		align: 'end',
	},
	{ key: 'actions', label: '', width: '2.5rem', align: 'end' },
]

const filters: ListViewFilter[] = [
	{
		key: 'status',
		label: 'Status',
		options: ['Open', 'Paid', 'Overdue'].map((value) => ({
			label: value,
			value,
		})),
	},
]
</script>

<template>
	<ListView
		:rows="rows"
		:columns="columns"
		:row-key="(inv) => inv.name"
		:active-key="activeName"
		:loading="loading"
		:filters="filters"
		:paginated="false"
		:show-count="false"
		searchable
		search-placeholder="Search by period or invoice number…"
		item-label="invoice"
		:empty-state="{
      title: 'No invoices yet',
      description: 'Your first invoice appears here at the end of the cycle.',
    }"
		:external-filter-active="dateActive"
		@clear-filters="range = []"
		@row-click="emit('rowClick', $event)"
	>
		<template #filters>
			<DateRangePicker
				v-model="range"
				class="flex-1 md:w-44"
				size="sm"
				format="D MMM"
				placeholder="Any date"
				:max="today"
			>
				<template #prefix>
					<span class="lucide-calendar size-4 text-ink-gray-4" />
				</template>
				<template #actions="{ setRange, clear, close }">
					<button
						v-for="p in datePresets"
						:key="p.label"
						type="button"
						class="w-full rounded-4 px-2 py-1.5 text-left text-base text-ink-gray-7 hover:bg-surface-gray-2"
						@click="() => { setRange(p.range()); close() }"
					>
						{{ p.label }}
					</button>
					<button
						type="button"
						class="w-full rounded-4 px-2 py-1.5 text-left text-base text-ink-gray-5 hover:bg-surface-gray-2"
						@click="() => { clear(); close() }"
					>
						Any date
					</button>
				</template>
			</DateRangePicker>
		</template>

		<template #invoice="{ row }">
			<div class="min-w-0 py-2.5">
				<p class="truncate text-base-medium text-ink-gray-9">
					{{ billingPeriod(row.period_start, row.period_end) }}
				</p>
				<p
					class="mt-1 truncate text-sm"
					:class="isOverdue(row) ? 'text-ink-red-7' : 'text-ink-gray-5'"
				>
					{{ isOverdue(row) ? `${row.name} · Due ${shortDate(row.due_date)}` : row.name }}
				</p>
			</div>
		</template>

		<template #status="{ row }">
			<Badge :theme="invoiceTheme(row.status)" :label="row.status" />
		</template>

		<template #total="{ row }">
			<span class="tabular-nums text-ink-gray-8">
				{{ money(row.total, row.currency) }}
			</span>
		</template>

		<template #actions="{ row }">
			<Button
				class="relative"
				variant="ghost"
				icon="lucide-download"
				:disabled="!row.has_pdf"
				:title="row.has_pdf ? 'Download PDF' : 'The PDF is ready once the invoice is issued'"
				label="Download invoice"
				@click="downloadInvoice(row.name)"
			/>
		</template>
	</ListView>
</template>
