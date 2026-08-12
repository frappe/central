<script setup lang="ts">
import { Badge, LoadingText, useCall } from 'frappe-ui'
import { computed, watch } from 'vue'
import { API, method } from '@/api/methods'
import SidePanel from '@/components/common/SidePanel.vue'
import { useSession } from '@/composables/useSession'
import { billingPeriod } from '@/lib/date'
import { invoiceTheme } from '@/lib/status'
import { money } from '@/lib/format'
import type { Statement } from '@/types/billing'

// The full statement line by line. The card carries the totals and the most
// recent few; a year of invoices belongs here rather than behind a scrollbar
// inside a card.
const open = defineModel<boolean>('open', { default: false })
const { activeTeam } = useSession()

const statement = useCall<Statement, { team: string }>({
	url: method(API.statement),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
})
watch(open, (isOpen) => {
	if (isOpen && activeTeam.value) statement.reload()
})

const loading = computed(() => statement.loading && !statement.data)
const data = computed(() => statement.data)
const currency = computed(() => data.value?.currency ?? 'INR')
// Newest first. The API returns the period ascending (it is a statement, and a
// statement is read forwards), but every history surface in the console — the
// card this tray opens from, the Invoices list, payments — puts the most recent
// row at the top, and the tray disagreeing with the card it came from is jarring.
const rows = computed(() => [...(data.value?.rows ?? [])].reverse())

</script>

<template>
	<SidePanel
		v-model:open="open"
		title="Statement of account"
		:subtitle="data ? billingPeriod(data.from_date, data.to_date) : undefined"
	>
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="6" />
		</div>
		<ul v-else-if="data" class="divide-y divide-outline-gray-1">
			<li
				v-for="row in rows"
				:key="row.invoice"
				class="grid grid-cols-[1fr_auto] items-start gap-3 px-4 py-3"
			>
				<div class="min-w-0">
					<span class="truncate text-p-sm text-ink-gray-8">
						{{ billingPeriod(row.period_start, row.period_end) }}
					</span>
					<p v-if="row.credit_applied" class="mt-0.5 text-p-sm text-ink-gray-5">
						{{ money(row.credit_applied, currency) }} from credits
					</p>
				</div>
				<div class="flex shrink-0 items-center gap-3">
					<Badge :theme="invoiceTheme(row.status)" variant="subtle" :label="row.status" />
					<span class="w-24 text-right text-p-sm tabular-nums text-ink-gray-9">
						{{ money(row.total, currency) }}
					</span>
				</div>
			</li>
		</ul>
	</SidePanel>
</template>
