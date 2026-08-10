<script setup lang="ts">
import dayjs from 'dayjs'
import { Badge, Button, DateRangePicker } from 'frappe-ui'
import { computed, h, ref } from 'vue'
import {
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import { billingPeriod, shortDate } from '@/lib/date'
import { money } from '@/lib/format'
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

const columns = computed<ListViewColumn<InvoiceSummary>[]>(() => [
	{
		id: 'invoice',
		// The accessor is what search matches on — the number and the period as
		// rendered ("May 2026"), per the placeholder's promise. Sorting stays
		// chronological via sortingFn; the name would sort alphabetically.
		accessorFn: (inv) =>
			`${inv.name} ${billingPeriod(inv.period_start, inv.period_end)}`,
		sortingFn: (a, b) =>
			(a.original.period_end || '').localeCompare(b.original.period_end || ''),
		header: 'Invoice',
		size: 260,
		cell: ({ row }) =>
			h('div', { class: 'min-w-0 py-2.5' }, [
				h(
					'p',
					{ class: 'truncate text-sm-medium text-ink-gray-8' },
					billingPeriod(row.original.period_start, row.original.period_end),
				),
				h(
					'p',
					{
						class: [
							'truncate text-p-sm',
							isOverdue(row.original) ? 'text-ink-red-8' : 'text-ink-gray-5',
						],
					},
					isOverdue(row.original)
						? `${row.original.name} · Due ${shortDate(row.original.due_date)}`
						: row.original.name,
				),
			]),
	},
	{
		accessorKey: 'status',
		header: 'Status',
		size: 110,
		meta: { align: 'end' },
		cell: ({ row }) =>
			h(Badge, {
				theme: invoiceTheme(row.original.status),
				variant: 'subtle',
				label: row.original.status,
			}),
	},
	{
		id: 'total',
		accessorFn: (inv) => inv.total,
		header: 'Amount',
		size: 110,
		meta: { align: 'end' },
		cell: ({ row }) =>
			h(
				'span',
				{ class: 'tabular-nums text-ink-gray-8' },
				money(row.original.total, row.original.currency),
			),
	},
	{
		id: 'actions',
		header: '',
		enableSorting: false,
		enableGlobalFilter: false,
		meta: { align: 'end' },
		// GROUNDING GAP (#70): no download endpoint yet — disabled until the
		// backend lands it. The wrapper stops a future click from also
		// selecting the row.
		cell: () =>
			h('span', { onClick: (e: Event) => e.stopPropagation() }, [
				h(Button, {
					variant: 'ghost',
					icon: 'lucide-download',
					disabled: true,
					title: 'Download PDF — coming soon',
					label: 'Download invoice',
				}),
			]),
	},
])

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
				class="w-44 shrink-0"
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
						class="w-full rounded px-2 py-1.5 text-left text-base text-ink-gray-7 hover:bg-surface-gray-2"
						@click="() => { setRange(p.range()); close() }"
					>
						{{ p.label }}
					</button>
					<button
						type="button"
						class="w-full rounded px-2 py-1.5 text-left text-base text-ink-gray-5 hover:bg-surface-gray-2"
						@click="() => { clear(); close() }"
					>
						Any date
					</button>
				</template>
			</DateRangePicker>
		</template>
	</ListView>
</template>
