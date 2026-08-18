<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { billingPeriod } from '@/lib/date'
import { formatDate, money, plural } from '@/lib/format'
import { attemptStory } from '@/lib/status'
import type { PaymentAttempt, Statement } from '@/types/billing'

const props = defineProps<{
	statement: Statement | null
	attempts: PaymentAttempt[] | null
}>()
const router = useRouter()

const currency = computed(() => props.statement?.currency ?? 'INR')
const earlier = computed(() =>
	Number(props.statement?.opening_outstanding ?? 0),
)
const outstanding = computed(
	() => Number(props.statement?.closing_outstanding ?? 0) + earlier.value,
)
const openRows = computed(() =>
	(props.statement?.rows ?? []).filter(
		(r) => r.status === 'Open' || r.status === 'Overdue',
	),
)
const hasOutstanding = computed(() => outstanding.value > 0)
const isOverdue = computed(() =>
	openRows.value.some((r) => r.status === 'Overdue'),
)

const story = computed(() => {
	const open = new Set(openRows.value.map((r) => r.invoice))
	return attemptStory(
		(props.attempts ?? []).filter((a) => a.invoice && open.has(a.invoice)),
	)
})

const preWindowInFlight = computed(() => {
	if (earlier.value <= 0) return null
	const windowInvoices = new Set(
		(props.statement?.rows ?? []).map((r) => r.invoice),
	)
	return (
		attemptStory(
			(props.attempts ?? []).filter(
				(a) => a.invoice && !windowInvoices.has(a.invoice),
			),
		).inFlight ?? null
	)
})

const title = computed(() => {
	const rows = openRows.value
	const head = `${money(outstanding.value, currency.value)} ${
		isOverdue.value ? 'overdue' : 'still outstanding'
	}`
	const label =
		rows.length === 0
			? 'on invoices from an earlier period'
			: rows.length === 1
				? `on your ${billingPeriod(rows[0].period_start, rows[0].period_end)} invoice`
				: `on ${plural(rows.length, 'open invoice')}`
	const andEarlier = earlier.value > 0 && rows.length ? ' and earlier invoices' : ''
	const s = story.value
	const inFlight = s.inFlight ?? preWindowInFlight.value
	if (inFlight)
		return `${head} ${label}${andEarlier} · payment processing since ${formatDate(inFlight.at)}`
	if (s.failed)
		return `${head} ${label}${andEarlier} · ${plural(s.failed, 'failed attempt')}`
	return `${head} ${label}${andEarlier}`
})

const action = computed(() => ({
	label:
		props.attempts === null || story.value.inFlight || preWindowInFlight.value
			? 'View invoice'
			: 'Pay now',
	onClick: () => {
		router.push({ name: 'BillingInvoices' })
	},
}))
</script>

<template>
	<Alert
		v-if="hasOutstanding"
		:title="title"
		:theme="isOverdue ? 'red' : 'amber'"
		:primary-action="action"
	/>
</template>
