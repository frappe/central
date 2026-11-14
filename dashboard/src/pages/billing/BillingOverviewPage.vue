<script setup lang="ts">
import { Alert, ScrollArea } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CollectionActionBanner from '@/components/billing/CollectionActionBanner.vue'
import CycleBreakdownPanel from '@/components/billing/CycleBreakdownPanel.vue'
import CycleFacts from '@/components/billing/CycleFacts.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import EstimatedCard from '@/components/billing/EstimatedCard.vue'
import GstStateBanner from '@/components/billing/GstStateBanner.vue'
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
import ResizeServerDialog from '@/components/servers/ResizeServerDialog.vue'
import TopupDialog from '@/components/TopupDialog.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingReports } from '@/composables/useBillingReports'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerMapData } from '@/composables/useServerMapData'
import { sessionReady, useSession } from '@/composables/useSession'
import { fetchBillingSetup } from '@/data/billingSetup'
import { parseTopupAmount } from '@/lib/topupAmount'

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
const topupAmount = ref<number>()

// The trial's Upgrade dialog opens here, so the customer stays on Billing.
const { servers } = useServerMapData()
const upgradeServerName = ref<string | null>(null)
const upgradeServer = computed(
	() =>
		servers.value.find((row) => row.name === upgradeServerName.value) ?? null,
)
const showUpgrade = computed({
	get: () => !!upgradeServer.value,
	set: (open: boolean) => {
		if (!open) upgradeServerName.value = null
	},
})

const onAddCredits = (amount?: number) => {
	topupAmount.value = amount
	if (requireSetup()) showTopup.value = true
}

// A top-up reminder links here with its team and the amount; billing managers get the dialog.
const route = useRoute()
const router = useRouter()
const { activeTeam, teams, setActiveTeam } = useSession()
const { canManageBilling, reload: reloadCapabilities } = useCapabilities()

const isOtherTeam = (team: unknown) =>
	team !== undefined && team !== activeTeam.value

async function openTopupLink(value: unknown) {
	await sessionReady
	const team = route.query.team
	if (isOtherTeam(team) && teams.value.some((row) => row.name === team)) {
		try {
			// Switching reloads the page with the same link, now on its team.
			setActiveTeam(team as string)
			return
		} catch {
			// No browser storage: stay on this team and drop the link.
		}
	}

	const { topup: _topup, team: _team, ...query } = route.query
	router.replace({ query })
	const amount = parseTopupAmount(value)
	if (!amount || !activeTeam.value || isOtherTeam(team)) return
	await Promise.all([fetchBillingSetup(activeTeam.value), reloadCapabilities()])
	if (canManageBilling.value) onAddCredits(amount)
}

watch(
	() => route.query.topup,
	(value) => {
		if (value !== undefined) void openTopupLink(value)
	},
	{ immediate: true },
)
</script>

<template>
	<div class="relative flex h-full min-h-0">
		<ScrollArea class="min-w-0 flex-1">
			<div
				class="grid auto-rows-max grid-cols-[min(64rem,100%)] content-start justify-center gap-3 px-3 pb-24 pt-3 [container-type:inline-size] md:gap-4 md:px-6 md:pt-7"
			>
				<OutstandingAlert
					:statement="reports.statement.data ?? null"
					:attempts="reports.attempts.data ?? null"
				/>
				<Alert
					v-if="!complete"
					theme="amber"
					title="Add your billing details"
					description="Currency, legal name, and address are needed to add credit, save a payment method, and provision servers."
					:primary-action="{ label: 'Add billing details', onClick: () => { setupDialogOpen = true } }"
				/>
				<CollectionActionBanner @add-credit="onAddCredits" />
				<TrialBillingBanner @upgrade="upgradeServerName = $event" />
				<GstStatusBanner @edit="setupDialogOpen = true" />
				<GstStateBanner @edit="setupDialogOpen = true" />

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
						@add-credit="onAddCredits()"
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
		</ScrollArea>

		<WalletHistoryPanel v-model:open="showWalletHistory" />
		<CycleBreakdownPanel v-model:open="showCycleBreakdown" />
		<PaymentSchedulePanel v-model:open="showSchedule" />
		<PayingForPanel v-model:open="showPayingFor" />
		<ProjectsPanel v-model:open="showProjects" />
		<TiersPanel v-model:open="showTiers" />
	</div>

	<EditBillingProfileDialog v-model="setupDialogOpen" />
	<TopupDialog
		v-model="showTopup"
		:currency="currency"
		:initial-amount="topupAmount"
		@done="reloadMoney"
	/>
	<ResizeServerDialog
		v-model:open="showUpgrade"
		:server="upgradeServer"
		@resized="reloadMoney"
	/>
</template>
