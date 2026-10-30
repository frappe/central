<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed, ref } from 'vue'
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
import PaymentSchedulePanel from '@/components/billing/PaymentSchedulePanel.vue'
import ProjectsPanel from '@/components/billing/ProjectsPanel.vue'
import SpendCard from '@/components/billing/SpendCard.vue'
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

const showTopup = ref(false)

const onAddCredits = () => {
	if (requireSetup()) showTopup.value = true
}
</script>

<template>
	<div class="relative flex h-full min-h-0">
		<div
			class="grid min-w-0 flex-1 auto-rows-max grid-cols-[min(64rem,100%)] content-start justify-center gap-3 overflow-y-auto px-3 pb-24 pt-3 [container-type:inline-size] md:gap-4 md:px-6 md:pt-7"
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

			<div class="grid gap-3 md:gap-4 lg:grid-cols-3">
				<EstimatedCard
					class="rounded-6 border border-outline-gray-1 lg:col-span-2"
					:active="showCycleBreakdown"
					@open="showCycleBreakdown = true"
					@open-tiers="showTiers = true"
				/>
				<CycleFacts
					class="rounded-6 border border-outline-gray-1"
					:outstanding="outstanding"
					:wallet-active="showWalletHistory"
					@open-schedule="showSchedule = true"
					@open-wallet="showWalletHistory = true"
					@add-credit="onAddCredits"
				/>
			</div>

			<PayingForCard
				@open="showPayingFor = true"
				@open-projects="showProjects = true"
			/>

			<SpendCard :reports="reports">
				<LimitsCard @open-tiers="showTiers = true" />
			</SpendCard>
		</div>

		<WalletHistoryPanel v-model:open="showWalletHistory" />
		<CycleBreakdownPanel v-model:open="showCycleBreakdown" />
		<PaymentSchedulePanel v-model:open="showSchedule" />
		<PayingForPanel v-model:open="showPayingFor" />
		<ProjectsPanel v-model:open="showProjects" />
		<TiersPanel v-model:open="showTiers" />
	</div>

	<EditBillingProfileDialog v-model="setupDialogOpen" />
	<TopupDialog v-model="showTopup" :currency="currency" @done="reloadMoney" />
</template>
