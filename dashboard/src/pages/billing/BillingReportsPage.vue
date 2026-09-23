<script setup lang="ts">
import { Button, LoadingText, TabButtons } from 'frappe-ui'
import { NumberCard } from 'frappe-ui/charts'
import { useRouter } from 'vue-router'
import BillingCard from '@/components/billing/BillingCard.vue'
import OutstandingAlert from '@/components/billing/OutstandingAlert.vue'
import RefundsCard from '@/components/billing/RefundsCard.vue'
import SpendHistoryCard from '@/components/billing/SpendHistoryCard.vue'
import SpendSplitCard from '@/components/billing/SpendSplitCard.vue'
import StatementCard from '@/components/billing/StatementCard.vue'
import StatementPanel from '@/components/billing/StatementPanel.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import {
	BILLING_REPORT_MONTHS,
	useBillingReports,
} from '@/composables/useBillingReports'
import { useTrayColumn } from '@/composables/useTrayColumn'

const router = useRouter()
const {
	months,
	history,
	statement,
	tax,
	attempts,
	symbol,
	creditsSymbol,
	taxSymbol,
	average,
	invoiceCaption,
	taxCaption,
	loading,
	statementLoading,
	taxLoading,
	neverBilled,
	exportUrl,
} = useBillingReports()

const MONTH_OPTIONS = BILLING_REPORT_MONTHS
type Tray = 'statement'
const { trayModel } = useTrayColumn<Tray>()
const showStatement = trayModel('statement')
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
							:export-url="exportUrl('spend')"
						/>
						<SpendSplitCard
							class="min-w-[20rem] flex-[2_1_0%]"
							:history="history.data"
						/>
					</div>

					<StatementCard
						:statement="statement.data ?? null"
						:loading="statementLoading"
						:export-url="exportUrl('statement')"
						@open="showStatement = true"
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
	</div>
</template>
