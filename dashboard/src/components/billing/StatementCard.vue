<script setup lang="ts">
import { Badge, Button, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import BillingCard from '@/components/billing/BillingCard.vue'
import { billingPeriod } from '@/lib/date'
import { capitalise, formatDate, money, plural } from '@/lib/format'
import { type AttemptStory, attemptStory, invoiceTheme } from '@/lib/status'
import type { PaymentAttempt, Statement, StatementRow } from '@/types/billing'

const VISIBLE = 5
const props = defineProps<{
	statement: Statement | null
	attempts: PaymentAttempt[]
	loading: boolean
	exportUrl: string
}>()
defineEmits<{ open: []; openPayments: [] }>()

const currency = computed(() => props.statement?.currency ?? 'INR')
const rows = computed(() =>
	(props.statement?.rows ?? []).slice(-VISIBLE).reverse(),
)
const hidden = computed(() =>
	Math.max(0, (props.statement?.rows?.length ?? 0) - VISIBLE),
)

const storyByInvoice = computed(() => {
	const grouped = new Map<string, PaymentAttempt[]>()
	for (const a of props.attempts) {
		if (!a.invoice) continue
		const list = grouped.get(a.invoice) ?? []
		list.push(a)
		grouped.set(a.invoice, list)
	}
	return new Map(
		[...grouped].map(([invoice, list]) => [invoice, attemptStory(list)]),
	)
})

function unsettledText(s: AttemptStory): string {
	if (s.inFlight) {
		const since = `${money(s.inFlight.amount, s.inFlight.currency)} processing since ${formatDate(s.inFlight.at)}`
		return s.failed
			? `${since} · ${plural(s.failed, 'failed retry', 'failed retries')}`
			: since
	}
	if (s.captured)
		return `${money(s.captured.amount, s.captured.currency)} paid ${formatDate(s.captured.at)}`
	if (s.failed) return plural(s.failed, 'failed attempt')
	return ''
}

function settledText(s: AttemptStory): string {
	if (s.captured) {
		const retries = s.failedBeforeCapture
			? ` · after ${plural(s.failedBeforeCapture, 'retry', 'retries')}`
			: ''
		const refund = s.refunded ? ` · refunded ${formatDate(s.refunded.at)}` : ''
		return `paid ${formatDate(s.captured.at)}${retries}${refund}`
	}
	if (s.refunded)
		return `${money(s.refunded.amount, s.refunded.currency)} refunded ${formatDate(s.refunded.at)}`
	return ''
}

function settledBy(row: StatementRow): string {
	const parts: string[] = []
	if (row.credit_applied > 0)
		parts.push(`${money(row.credit_applied, currency.value)} from credits`)
	const unsettled = row.status === 'Open' || row.status === 'Overdue'
	const story = storyByInvoice.value.get(row.invoice)
	let text = story
		? unsettled
			? unsettledText(story)
			: settledText(story)
		: ''
	if (!text && !unsettled && row.amount_paid > 0)
		text = `${money(row.amount_paid, currency.value)} paid`
	if (text) parts.push(text)
	return capitalise(parts.join(' · '))
}
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
				<div
					v-if="rows.length"
					class="grid grid-cols-[7.5rem_1fr_5rem_7rem] items-center gap-3 pb-2 pt-3 text-xs uppercase tracking-wide text-ink-gray-4"
				>
					<span>Period</span>
					<span>Settled by</span>
					<span class="text-right">Status</span>
					<span class="text-right">Amount</span>
				</div>

				<ul
					v-if="rows.length"
					class="divide-y divide-outline-gray-1 border-t border-outline-gray-1"
				>
					<li
						v-for="row in rows"
						:key="row.invoice"
						class="grid grid-cols-[7.5rem_1fr_5rem_7rem] items-center gap-3 py-2.5"
					>
						<span
							class="truncate text-p-sm text-ink-gray-8"
							:title="billingPeriod(row.period_start, row.period_end)"
						>
							{{ billingPeriod(row.period_start, row.period_end) }}
						</span>
						<span class="truncate text-p-sm text-ink-gray-6">
							{{ settledBy(row) || '—' }}
						</span>
						<span class="flex justify-end">
							<Badge
								:theme="invoiceTheme(row.status)"
								variant="subtle"
								:label="row.status"
							/>
						</span>
						<span class="text-right text-p-sm tabular-nums text-ink-gray-9">
							{{ money(row.total, currency) }}
						</span>
					</li>
				</ul>

				<p v-else class="py-2 text-p-sm text-ink-gray-5">
					No invoices in this period.
				</p>
			</template>

			<p v-else class="py-2 text-p-sm text-ink-gray-5">
				Couldn't load the statement. The payment log below still works.
			</p>

			<!-- Says what it is. The statutory tax invoice is issued by ERPNext
			     (ADR 0019) and we cannot hand it over yet, so this must not imply a
			     download that does not exist (#70). -->
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
					<!-- Payment log door parked (user call, 2026-08-18); the
					     openPayments emit and its tray stay wired. -->
				</div>
				<p class="ml-auto text-p-sm text-ink-gray-5">
					For reconciling against your own records. Tax invoices are issued
					separately.
				</p>
			</div>
		</template>
	</BillingCard>
</template>
