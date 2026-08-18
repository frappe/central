<script setup lang="ts">
import { Button, dayjs, LoadingText, TabButtons, useCall } from 'frappe-ui'
import { NumberCard } from 'frappe-ui/charts'
import { computed, provide, ref } from 'vue'
import { useRouter } from 'vue-router'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import OutstandingAlert from '@/components/billing/OutstandingAlert.vue'
import PaymentHistoryPanel from '@/components/billing/PaymentHistoryPanel.vue'
import RefundsCard from '@/components/billing/RefundsCard.vue'
import SpendHistoryCard from '@/components/billing/SpendHistoryCard.vue'
import SpendSplitCard from '@/components/billing/SpendSplitCard.vue'
import StatementCard from '@/components/billing/StatementCard.vue'
import StatementPanel from '@/components/billing/StatementPanel.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { currencySymbol, money, plural } from '@/lib/format'
import type {
	PaymentAttempt,
	SpendHistory,
	Statement,
	TaxSummary,
} from '@/types/billing'

const { activeTeam } = useSession()
const router = useRouter()

const MONTH_OPTIONS = [
	{ label: '3 months', value: 3 },
	{ label: '6 months', value: 6 },
	{ label: '12 months', value: 12 },
]
const months = ref(12)

const fromDate = computed(() =>
	dayjs()
		.subtract(months.value - 1, 'month')
		.startOf('month')
		.format('YYYY-MM-DD'),
)

const history = useCall<SpendHistory, { team: string; months: number }>({
	url: method(API.spendHistory),
	params: () => ({ team: activeTeam.value!, months: months.value }),
	immediate: false,
	refetch: true,
})
const statement = useCall<Statement, { team: string; from_date: string }>({
	url: method(API.statement),
	params: () => ({ team: activeTeam.value!, from_date: fromDate.value }),
	immediate: false,
	refetch: true,
})
const tax = useCall<TaxSummary, { team: string; from_date: string }>({
	url: method(API.taxSummary),
	params: () => ({ team: activeTeam.value!, from_date: fromDate.value }),
	immediate: false,
	refetch: true,
})
const attempts = useCall<PaymentAttempt[], { team: string; limit: number }>({
	url: method(API.paymentAttempts),
	params: () => ({ team: activeTeam.value!, limit: 1000 }),
	immediate: false,
	refetch: true,
})

whenTeamReady(() => {
	history.reload()
	statement.reload()
	tax.reload()
	attempts.reload()
})

const currency = computed(() => history.data?.currency ?? 'INR')
const symbol = computed(() => currencySymbol(currency.value))
const creditsSymbol = computed(() =>
	currencySymbol(statement.data?.currency ?? currency.value),
)
const taxSymbol = computed(() =>
	currencySymbol(tax.data?.currency ?? currency.value),
)

const average = computed(() => {
	const billed = (history.data?.months ?? []).filter((m) => m.total > 0)
	if (!billed.length) return 0
	return billed.reduce((sum, m) => sum + m.total, 0) / billed.length
})

const invoiceCaption = computed(
	() => `across ${plural(history.data?.invoice_count ?? 0, 'invoice')}`,
)

const taxCaption = computed(() => {
	const d = tax.data
	if (!d) return ''
	if (d.total_withheld > 0)
		return `plus ${money(d.total_withheld, d.currency)} withheld at source`
	if ((d.total_tax ?? 0) <= 0) return 'none charged in this period'
	const charged = d.by_type.filter(
		(t) => t.tax_type !== 'No tax' && t.tax_type !== 'Zero-rated',
	)
	if (charged.length === 1) {
		const t = charged[0]
		return `${t.tax_type} on ${money(t.taxable, d.currency)}`
	}
	return `across ${charged.length} tax types`
})

// One docked tray at a time, same as Overview: the panel column is a single
type Tray = 'payments' | 'statement' | null
const tray = ref<Tray>(null)
const traySwitching = ref(false)
provide('side-panel-switching', traySwitching)
function trayModel(name: Exclude<Tray, null>) {
	return computed({
		get: () => tray.value === name,
		set: (open: boolean) => {
			if (open) {
				traySwitching.value = tray.value !== null && tray.value !== name
				tray.value = name
				statement.reload()
				attempts.reload()
			} else if (tray.value === name) {
				traySwitching.value = false
				tray.value = null
			}
		},
	})
}
const showPayments = trayModel('payments')
const showStatement = trayModel('statement')

const loading = computed(() => history.loading && !history.data)
const statementLoading = computed(() => statement.loading && !statement.data)
const taxLoading = computed(() => tax.loading && !tax.data)
const attemptsLoading = computed(() => attempts.loading && !attempts.data)
const hasDebt = computed(() => {
	const s = statement.data
	if (!s) return false
	return (
		Number(s.closing_outstanding ?? 0) + Number(s.opening_outstanding ?? 0) > 0
	)
})
const neverBilled = computed(
	() =>
		!loading.value &&
		!!history.data &&
		months.value === 12 &&
		history.data.invoice_count === 0 &&
		!hasDebt.value,
)

// Export goes through a plain link, not fetch: the endpoint sets a binary
// response and the browser's own download handling is the right thing here.
function exportUrl(report: string, windowed = true): string {
	const team = encodeURIComponent(activeTeam.value ?? '')
	const range = windowed ? `&from_date=${fromDate.value}` : ''
	return `/api/method/${API.exportCsv}?report=${report}&team=${team}${range}`
}
</script>

<template>
	<div class="flex h-full min-h-0">
		<div class="min-w-0 flex-1 overflow-y-auto">
			<div class="mx-auto w-full max-w-5xl space-y-5 px-6 py-8">
				<div v-if="loading" class="space-y-5">
					<BillingCard v-for="i in 2" :key="i" title=" ">
						<LoadingText :lines="4" />
					</BillingCard>
				</div>

				<!-- One first-run state for the whole page. -->
				<EmptyState
					v-else-if="neverBilled"
					icon="lucide-chart-no-axes-column"
					title="No billing history yet"
					description="Your spend, payments and tax show up here after your first invoice."
				>
					<template #action>
						<Button
							variant="subtle"
							label="Go to billing overview"
							@click="router.push({ name: 'Billing' })"
						/>
						<PaymentHistoryCard
							:export-url="exportUrl('payments')"
							@open="showPayments = true"
						/>
						<RefundsCard />
						<TaxSummaryCard />
					</template>
				</EmptyState>

				<EmptyState
					v-else-if="!history.data"
					icon="lucide-chart-no-axes-column"
					title="Couldn't load reports"
					description="Something went wrong on our side."
				>
					<template #action>
						<Button variant="subtle" label="Retry" @click="history.reload()" />
					</template>
				</EmptyState>

				<template v-else>
					<OutstandingAlert
						:statement="statement.data ?? null"
						:attempts="attempts.data ?? null"
					/>

					<TabButtons v-model="months" :options="MONTH_OPTIONS" />

					<div class="flex flex-wrap gap-4">
						<NumberCard
							class="min-w-44 flex-1"
							title="Total spend"
							:value="history.data?.total ?? null"
							:prefix="symbol"
							:precision="2"
							:delta-caption="invoiceCaption"
							:loading="loading"
						/>
						<NumberCard
							class="min-w-44 flex-1"
							title="Average month"
							:value="history.data ? average : null"
							:prefix="symbol"
							:precision="2"
							delta-caption="in months with billing"
							:loading="loading"
						/>
						<NumberCard
							class="min-w-44 flex-1"
							title="Paid by credits"
							:value="statement.data?.settled_by_credits ?? null"
							:prefix="creditsSymbol"
							:precision="2"
							delta-caption="from your wallet"
							:loading="statementLoading"
						/>
						<NumberCard
							class="min-w-44 flex-1"
							title="Tax charged"
							:value="tax.data?.total_tax ?? null"
							:prefix="taxSymbol"
							:precision="2"
							:delta-caption="taxCaption"
							:loading="taxLoading"
						/>
					</div>

					<div class="flex flex-wrap gap-5">
						<SpendHistoryCard
							class="min-w-[24rem] flex-[3_1_0%]"
							:history="history.data"
							:export-url="exportUrl('spend', false)"
						/>
						<SpendSplitCard
							class="min-w-[20rem] flex-[2_1_0%]"
							:history="history.data"
						/>
					</div>

					<StatementCard
						:statement="statement.data ?? null"
						:attempts="attempts.data ?? []"
						:loading="statementLoading"
						:export-url="exportUrl('statement')"
						@open="showStatement = true"
						@open-payments="showPayments = true"
					/>
					<RefundsCard />
				</template>
			</div>
		</div>

		<StatementPanel
			v-model:open="showStatement"
			:statement="statement.data ?? null"
			:loading="statementLoading"
		/>
		<PaymentHistoryPanel
			v-model:open="showPayments"
			:attempts="attempts.data ?? null"
			:loading="attemptsLoading"
			:export-url="exportUrl('payments', false)"
		/>
	</div>
</template>
