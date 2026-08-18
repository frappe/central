<script setup lang="ts">
import { Button, LoadingText, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { API, method } from '@/api/methods'
import BillingCard from '@/components/billing/BillingCard.vue'
import PaymentHistoryCard from '@/components/billing/PaymentHistoryCard.vue'
import PaymentHistoryPanel from '@/components/billing/PaymentHistoryPanel.vue'
import RefundsCard from '@/components/billing/RefundsCard.vue'
import SpendHistoryCard from '@/components/billing/SpendHistoryCard.vue'
import SpendSplitCard from '@/components/billing/SpendSplitCard.vue'
import StatementCard from '@/components/billing/StatementCard.vue'
import StatementPanel from '@/components/billing/StatementPanel.vue'
import TaxSummaryCard from '@/components/billing/TaxSummaryCard.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import type { SpendHistory } from '@/types/billing'

// Billing › Reports — the team's own record ACROSS periods. Everything on
// Overview is scoped to the current cycle and its trays explain that cycle; what
// genuinely doesn't fit there is history, and that is all this page is.
//
// The page owns the period, and one read (spend history) decides whether there is
// anything to report at all: a team with no invoices meets ONE first-run state,
// not five empty cards and a flat chart. That is deliberate — a grid of zeroes
// reads as breakage, and a new customer's first impression of billing shouldn't be
// something that looks broken.
const { activeTeam } = useSession()
const router = useRouter()

const MONTH_OPTIONS = [
	{ label: '3 months', value: 3 },
	{ label: '6 months', value: 6 },
	{ label: '12 months', value: 12 },
]
const months = ref(12)

const history = useCall<SpendHistory, { team: string; months: number }>({
	url: method(API.spendHistory),
	params: () => ({ team: activeTeam.value!, months: months.value }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => history.reload())

function setMonths(value: number): void {
	months.value = value
	history.reload()
}

// One docked tray at a time, same as Overview: the panel column is a single
// 24rem slot. A card that outgrows its five rows hands the rest to a tray rather
// than growing a scrollbar of its own.
type Tray = 'payments' | 'statement' | null
const tray = ref<Tray>(null)
function trayModel(name: Exclude<Tray, null>) {
	return computed({
		get: () => tray.value === name,
		set: (open: boolean) => {
			tray.value = open ? name : null
		},
	})
}
const showPayments = trayModel('payments')
const showStatement = trayModel('statement')

const loading = computed(() => history.loading && !history.data)
// Nothing has ever been billed — not "nothing this month". The distinction is
// what separates a first-run state from a quiet period.
const neverBilled = computed(
	() => !loading.value && (history.data?.invoice_count ?? 0) === 0,
)

// Export goes through a plain link, not fetch: the endpoint sets a binary
// response and the browser's own download handling is the right thing here.
function exportUrl(report: string): string {
	const team = encodeURIComponent(activeTeam.value ?? '')
	return `/api/method/${API.exportCsv}?report=${report}&team=${team}`
}
</script>

<template>
	<div class="flex h-full min-h-0">
		<div class="min-w-0 flex-1 overflow-y-auto">
			<div class="mx-auto w-full max-w-3xl space-y-5 px-6 py-8">
				<header class="flex flex-wrap items-end justify-between gap-3">
					<div>
						<h1 class="text-lg-semibold text-ink-gray-9">Reports</h1>
						<p class="mt-0.5 text-p-sm text-ink-gray-5">
							Your billing history: what you've spent, paid and been charged
							tax on.
						</p>
					</div>
					<div v-if="!neverBilled" class="flex items-center gap-2">
						<div
							class="flex overflow-hidden rounded-5 border border-outline-gray-2"
						>
							<button
								v-for="opt in MONTH_OPTIONS"
								:key="opt.value"
								type="button"
								class="border-r border-outline-gray-2 px-2.5 py-1 text-p-sm last:border-r-0 transition-colors"
								:class="
                months === opt.value
                  ? 'bg-surface-gray-2 text-ink-gray-9'
                  : 'text-ink-gray-6 hover:bg-surface-gray-1'
              "
								@click="setMonths(opt.value)"
							>
								{{ opt.label }}
							</button>
						</div>
						<Button
							variant="subtle"
							size="sm"
							:link="exportUrl('statement')"
							label="Export CSV"
						>
							<template #prefix>
								<span class="lucide-download size-4" aria-hidden="true" />
							</template>
						</Button>
					</div>
				</header>

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
					description="Once your first invoice is issued, this page shows what you've spent month by month, where it went, and everything you've paid."
				>
					<template #action>
						<Button
							variant="subtle"
							label="Go to billing overview"
							@click="router.push({ name: 'Billing' })"
						/>
					</template>
				</EmptyState>

				<template v-else>
					<SpendHistoryCard :history="history.data!" />
					<SpendSplitCard :history="history.data!" />
					<StatementCard
						:export-url="exportUrl('statement')"
						@open="showStatement = true"
					/>
					<PaymentHistoryCard
						:export-url="exportUrl('payments')"
						@open="showPayments = true"
					/>
					<RefundsCard />
					<TaxSummaryCard />
				</template>
			</div>
		</div>

		<StatementPanel v-model:open="showStatement" />
		<PaymentHistoryPanel v-model:open="showPayments" />
	</div>
</template>
