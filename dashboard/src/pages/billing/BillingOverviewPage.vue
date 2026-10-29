<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed, ref } from 'vue'
import BillingContactTaxCard from '@/components/billing/BillingContactTaxCard.vue'
import CollectionActionBanner from '@/components/billing/CollectionActionBanner.vue'
import CycleBreakdownPanel from '@/components/billing/CycleBreakdownPanel.vue'
import CycleFacts from '@/components/billing/CycleFacts.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import EstimatedCard from '@/components/billing/EstimatedCard.vue'
import GstStatusBanner from '@/components/billing/GstStatusBanner.vue'
import LimitsCard from '@/components/billing/LimitsCard.vue'
import OutstandingAlert from '@/components/billing/OutstandingAlert.vue'
import PayingForCard from '@/components/billing/PayingForCard.vue'
import PayingForPanel from '@/components/billing/PayingForPanel.vue'
import PaymentMethodsCard from '@/components/billing/PaymentMethodsCard.vue'
import PaymentSchedulePanel from '@/components/billing/PaymentSchedulePanel.vue'
import ProjectsPanel from '@/components/billing/ProjectsPanel.vue'
import RefundsCard from '@/components/billing/RefundsCard.vue'
import SpendCard from '@/components/billing/SpendCard.vue'
import StatementCard from '@/components/billing/StatementCard.vue'
import StatementPanel from '@/components/billing/StatementPanel.vue'
import StopBillingCard from '@/components/billing/StopBillingCard.vue'
import TiersPanel from '@/components/billing/TiersPanel.vue'
import TrialBillingBanner from '@/components/billing/TrialBillingBanner.vue'
import WalletHistoryPanel from '@/components/billing/WalletHistoryPanel.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingReports } from '@/composables/useBillingReports'
import { useBillingSetup } from '@/composables/useBillingSetup'

const { complete, setupDialogOpen, requireSetup } = useBillingSetup()
const { currency, reloadMoney } = useBillingOverview()
const reports = useBillingReports()

const outstanding = computed(() => {
	const statement = reports.statement.data

	return (
		Number(statement?.closing_outstanding ?? 0) +
		Number(statement?.opening_outstanding ?? 0)
	)
})

type Tray =
	| 'wallet'
	| 'cycle'
	| 'schedule'
	| 'payingFor'
	| 'projects'
	| 'tiers'
	| 'statement'
	| null

const tray = ref<Tray>(null)

const trayModel = (name: Exclude<Tray, null>) =>
	computed({
		get: () => tray.value === name,
		set: (open: boolean) => {
			tray.value = open ? name : null
		},
	})

const showWalletHistory = trayModel('wallet')
const showCycleBreakdown = trayModel('cycle')
const showSchedule = trayModel('schedule')
const showPayingFor = trayModel('payingFor')
const showProjects = trayModel('projects')
const showTiers = trayModel('tiers')
const showStatement = trayModel('statement')

const showTopup = ref(false)

const onAddCredits = () => {
	if (requireSetup()) showTopup.value = true
}
</script>

<template>
	<div class="relative flex h-full min-h-0">
		<div
			class="grid min-w-0 flex-1 auto-rows-max grid-cols-[min(64rem,100%)] content-start justify-center gap-4 overflow-y-auto px-3 pb-24 pt-3 [container-type:inline-size] md:gap-5 md:px-6 md:pt-7"
		>
			<Alert
				v-if="!complete"
				theme="amber"
				title="Add your billing details"
				description="Currency, legal name, and address are needed to add credit, save a payment method, and provision servers."
				:primary-action="{ label: 'Add billing details', onClick: () => { setupDialogOpen = true } }"
			/>
			<OutstandingAlert
				:statement="reports.statement.data ?? null"
				:attempts="reports.attempts.data ?? null"
			/>
			<CollectionActionBanner />
			<TrialBillingBanner />
			<GstStatusBanner @edit="setupDialogOpen = true" />

			<section
				class="grid overflow-hidden rounded-6 border border-outline-gray-1 bg-surface-base [@container_(min-width:46rem)]:grid-cols-[minmax(0,1fr)_19rem]"
			>
				<EstimatedCard
					:active="showCycleBreakdown"
					@open="showCycleBreakdown = true"
					@open-tiers="showTiers = true"
				/>
				<CycleFacts
					class="border-t border-outline-gray-1 [@container_(min-width:46rem)]:border-l [@container_(min-width:46rem)]:border-t-0"
					:outstanding="outstanding"
					:schedule-active="showSchedule"
					:wallet-active="showWalletHistory"
					@open-schedule="showSchedule = true"
					@open-wallet="showWalletHistory = true"
					@add-credit="onAddCredits"
				/>
			</section>

			<SpendCard :reports="reports" />
			<LimitsCard @open-tiers="showTiers = true" />
			<PayingForCard
				@open="showPayingFor = true"
				@open-projects="showProjects = true"
			/>

			<div
				class="grid gap-4 md:gap-5 [@container_(min-width:50rem)]:grid-cols-2"
			>
				<PaymentMethodsCard />
				<BillingContactTaxCard @edit="setupDialogOpen = true" />
			</div>

			<StatementCard
				:statement="reports.statement.data ?? null"
				:loading="reports.statementLoading.value"
				:export-url="reports.exportUrl('statement')"
				@open="showStatement = true"
			/>
			<RefundsCard />
			<StopBillingCard />
		</div>

		<WalletHistoryPanel v-model:open="showWalletHistory" />
		<CycleBreakdownPanel v-model:open="showCycleBreakdown" />
		<PaymentSchedulePanel v-model:open="showSchedule" />
		<PayingForPanel v-model:open="showPayingFor" />
		<ProjectsPanel v-model:open="showProjects" />
		<TiersPanel v-model:open="showTiers" />
		<StatementPanel
			v-model:open="showStatement"
			:statement="reports.statement.data ?? null"
			:loading="reports.statementLoading.value"
		/>
	</div>

	<EditBillingProfileDialog v-model="setupDialogOpen" />
	<TopupDialog v-model="showTopup" :currency="currency" @done="reloadMoney" />
</template>
