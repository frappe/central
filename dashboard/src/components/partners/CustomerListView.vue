<script setup lang="ts">
import { Avatar, Badge, type DropdownOptions } from 'frappe-ui'
import { computed, ref } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
	type ListViewFilter,
} from '@/components/common/list-view'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import TranslatedText from '@/components/common/TranslatedText.vue'
import {
	isPartnerPaying,
	nextPayerChangeDay,
} from '@/composables/usePartnerLinks'
import { formatDate, money } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { CustomerLink } from '@/types/api'

interface CustomerListViewProps {
	rows: CustomerLink[]
	loading: boolean
	error: string
	/** A partner manager accepts, declines, or stops paying, and ends links. */
	canManage: boolean
	/** Opens the partner team's own bill, which carries the customers it pays for. */
	canViewBilling: boolean
}

const props = defineProps<CustomerListViewProps>()

const emit = defineEmits<{
	open: [row: CustomerLink]
	viewBill: [row: CustomerLink]
	accept: [row: CustomerLink]
	decline: [row: CustomerLink]
	stopPaying: [row: CustomerLink]
	end: [row: CustomerLink]
	retry: []
}>()

const query = ref(createListViewQuery({ pageSize: 20 }))

const isRequest = (row: CustomerLink) =>
	row.status === 'Active' && row.payer === 'Partner Requested'

// A pay request waits on the partner, so it leads. Ended links sink to the end.
const rank = (row: CustomerLink) =>
	isRequest(row) ? 0 : row.status === 'Active' ? 1 : 2

const sortedRows = computed(() =>
	[...props.rows].sort((a, b) => rank(a) - rank(b)),
)

const STATUS_DOTS: Record<CustomerLink['status'], string> = {
	Active: 'var(--ink-green-6)',
	Ended: 'var(--ink-gray-5)',
}

const filters: ListViewFilter[] = [
	{
		key: 'status',
		label: __('Status'),
		allLabel: __('All statuses'),
		options: [
			{ label: __('Active'), value: 'Active' },
			{ label: __('Ended'), value: 'Ended' },
		],
	},
]

/** Who pays this month, and the date that changes it. */
function getBilling(row: CustomerLink): { payer: string; note: string } {
	const you = __('You')
	if (row.status === 'Ended') return { payer: '', note: '' }
	if (isRequest(row))
		return {
			payer: '',
			note: __('From {0} if you accept', [formatDate(nextPayerChangeDay())]),
		}
	if (row.payer === 'Partner')
		return isPartnerPaying(row)
			? {
					payer: you,
					note: __('Since {0}', [formatDate(row.partner_pays_from)]),
				}
			: {
					payer: __('Customer'),
					note: __('You pay from {0}', [formatDate(row.partner_pays_from)]),
				}
	if (isPartnerPaying(row))
		return {
			payer: you,
			note: __('Until {0}', [formatDate(row.partner_pays_until)]),
		}
	return { payer: __('Customer'), note: '' }
}

const columns: ListViewColumn<CustomerLink>[] = [
	{
		key: 'customer_name',
		label: __('Customer'),
		value: (row) => `${row.customer_name} ${row.customer_email}`,
		width: 'minmax(14rem,2fr)',
		sortable: true,
	},
	{
		key: 'status',
		label: __('Status'),
		value: (row) => row.status,
		width: 'minmax(7rem,0.8fr)',
		sortable: true,
	},
	{
		key: 'role',
		label: __('Access'),
		value: (row) => row.role,
		width: 'minmax(8rem,1fr)',
		sortable: true,
	},
	{
		key: 'payer',
		label: __('Billing'),
		value: (row) => getBilling(row).payer,
		width: 'minmax(10rem,1fr)',
		sortable: true,
	},
	{
		key: 'mrr',
		label: __('MRR'),
		value: (row) => row.mrr ?? 0,
		width: 'minmax(7rem,0.8fr)',
		align: 'end',
		sortable: true,
	},
	{
		key: 'server_count',
		label: __('Servers'),
		value: (row) => row.server_count ?? 0,
		width: '5rem',
		align: 'end',
		sortable: true,
	},
	{ key: 'actions', label: '', width: '2.5rem', align: 'end' },
]

/** One unlabelled menu section per kind of action, the destructive one last. */
function getMenu(row: CustomerLink): DropdownOptions {
	const go = []
	if (row.can_open)
		go.push({
			label: __('Open team'),
			icon: 'lucide-arrow-up-right',
			onClick: () => emit('open', row),
		})
	if (props.canViewBilling && isPartnerPaying(row))
		go.push({
			label: __("View this month's bill"),
			icon: 'lucide-receipt',
			onClick: () => emit('viewBill', row),
		})
	go.push({
		label: __('Email owner'),
		icon: 'lucide-mail',
		onClick: () => window.open(`mailto:${row.customer_email}`),
	})

	const manage = []
	const ending = []
	if (props.canManage && row.status === 'Active') {
		if (isRequest(row))
			manage.push(
				{
					label: __('Accept paying'),
					icon: 'lucide-check',
					onClick: () => emit('accept', row),
				},
				{
					label: __('Decline request'),
					icon: 'lucide-x',
					onClick: () => emit('decline', row),
				},
			)
		if (row.payer === 'Partner')
			manage.push({
				label: __('Stop paying'),
				icon: 'lucide-wallet',
				onClick: () => emit('stopPaying', row),
			})
		ending.push({
			label: __('End link'),
			icon: 'lucide-unlink',
			theme: 'red',
			onClick: () => emit('end', row),
		})
	}

	return [go, manage, ending]
		.filter((items) => items.length)
		.map((items, index) => ({
			group: `${index}`,
			hideLabel: true,
			options: items,
		}))
}
</script>

<template>
	<ListView
		v-model:query="query"
		flush
		min-width="48rem"
		:rows="sortedRows"
		:filters="filters"
		:columns="columns"
		:row-key="(row) => row.name"
		:loading="loading"
		:error="error"
		searchable
		:search-placeholder="__('Search customers')"
		item-label="customer"
		row-class="min-h-14 py-2"
		:empty-state="{
			title: __('No customers yet'),
			description: __('A customer adds you on Frappe Cloud with your partner code.'),
		}"
		@retry="emit('retry')"
	>
		<template #customer_name="{ row }">
			<span class="flex min-w-0 items-center gap-3">
				<Avatar
					:image="row.customer_logo ?? undefined"
					:label="row.customer_name"
					size="lg"
					shape="square"
				/>
				<span class="flex min-w-0 flex-col gap-1">
					<span class="truncate text-sm-medium leading-none text-ink-gray-9">
						{{ row.customer_name }}
					</span>
					<span class="truncate text-xs leading-none text-ink-gray-5">
						{{ row.customer_email }}
					</span>
				</span>
			</span>
		</template>

		<template #status="{ row }">
			<span class="flex min-w-0 flex-col gap-1">
				<span
					class="flex items-center gap-2 text-sm leading-none text-ink-gray-7"
				>
					<span
						class="size-2 shrink-0 rounded-full"
						:style="{ background: STATUS_DOTS[row.status] }"
					/>
					{{ row.status === 'Active' ? __('Active') : __('Ended') }}
				</span>
				<span
					v-if="row.status === 'Ended'"
					class="truncate text-xs leading-none tabular-nums text-ink-gray-5"
				>
					{{ formatDate(row.ended_on) }}
				</span>
			</span>
		</template>

		<template #role="{ row }">
			<span class="flex min-w-0 flex-col gap-1">
				<span class="truncate text-sm leading-none text-ink-gray-7">
					{{ row.role }}
				</span>
				<span
					class="truncate text-xs leading-none tabular-nums text-ink-gray-5"
				>
					{{ __('Since {0}', [formatDate(row.linked_on)]) }}
				</span>
			</span>
		</template>

		<template #payer="{ row }">
			<span class="flex min-w-0 flex-col items-start gap-1">
				<Badge
					v-if="isRequest(row)"
					theme="orange"
					variant="subtle"
					:label="__('Asked you to pay')"
				/>
				<span
					v-else-if="getBilling(row).payer"
					class="truncate text-sm leading-none text-ink-gray-7"
				>
					<TranslatedText :text="__('Paid by {0}')">
						<template #0>
							<span class="text-sm-semibold text-ink-gray-9">
								{{ getBilling(row).payer }}
							</span>
						</template>
					</TranslatedText>
				</span>
				<span
					v-if="getBilling(row).note"
					class="truncate text-xs leading-none tabular-nums text-ink-gray-5"
				>
					{{ getBilling(row).note }}
				</span>
			</span>
		</template>

		<template #mrr="{ row }">
			<span
				:class="[
					'truncate text-sm tabular-nums',
					row.mrr ? 'text-ink-gray-8' : 'text-ink-gray-4',
				]"
			>
				{{ row.mrr == null ? '-' : money(row.mrr, row.currency ?? undefined) }}
			</span>
		</template>

		<template #server_count="{ row }">
			<span class="text-sm tabular-nums text-ink-gray-7">
				{{ row.server_count ?? '-' }}
			</span>
		</template>

		<template #actions="{ row }">
			<RowActionsMenu
				:options="getMenu(row)"
				:label="__('Actions for {0}', [row.customer_name])"
			/>
		</template>
	</ListView>
</template>
