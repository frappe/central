<script setup lang="ts">
import { Button } from 'frappe-ui'
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
const unsettledRows = computed(() =>
	(props.statement?.rows ?? []).filter(
		(r) => r.status === 'Outstanding' || r.status === 'Overdue',
	),
)
// Only an issued invoice is owed. One not issued yet is still being prepared.
const openRows = computed(() => unsettledRows.value.filter((r) => r.is_issued))
const hasOutstanding = computed(() => outstanding.value > 0)
const allHeld = computed(
	() => unsettledRows.value.length > 0 && openRows.value.length === 0,
)
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
	const andEarlier =
		earlier.value > 0 && rows.length ? ' and earlier invoices' : ''
	return `${head} ${label}${andEarlier}`
})
const detail = computed(() => {
	const inFlight = story.value.inFlight ?? preWindowInFlight.value
	if (inFlight) return `Payment processing since ${formatDate(inFlight.at)}.`
	if (story.value.failed)
		return `${plural(story.value.failed, 'payment attempt')} failed. Pay now to keep your servers running.`
	return isOverdue.value ? 'Pay now to keep your servers running.' : ''
})

const action = computed(() => ({
	label:
		props.attempts === null ||
		story.value.inFlight ||
		preWindowInFlight.value ||
		allHeld.value
			? 'View invoice'
			: 'Pay now',
	onClick: () => {
		router.push({ name: 'BillingInvoices' })
	},
}))
</script>

<template>
	<section
		v-if="hasOutstanding"
		role="alert"
		class="flex flex-wrap items-center gap-3.5 rounded-6 border px-4 py-3.5"
		:class="
			isOverdue
				? 'border-outline-red-2 bg-surface-red-1'
				: 'border-outline-amber-2 bg-surface-amber-1'
		"
	>
		<span
			class="grid size-8 shrink-0 place-items-center rounded-4"
			:class="isOverdue ? 'bg-surface-red-2' : 'bg-surface-amber-2'"
		>
			<span
				class="lucide-circle-alert size-4"
				:class="isOverdue ? 'text-ink-red-6' : 'text-ink-amber-6'"
				aria-hidden="true"
			/>
		</span>
		<div class="min-w-0 flex-[1_1_20rem]">
			<p
				class="text-p-base-medium"
				:class="isOverdue ? 'text-ink-red-8' : 'text-ink-amber-8'"
			>
				{{ title }}
			</p>
			<p
				v-if="detail"
				class="mt-0.5 text-p-sm"
				:class="isOverdue ? 'text-ink-red-6' : 'text-ink-amber-6'"
			>
				{{ detail }}
			</p>
		</div>
		<Button variant="solid" :label="action.label" @click="action.onClick" />
	</section>
</template>
