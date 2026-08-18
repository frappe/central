<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed, ref } from 'vue'
import BillingContactTaxCard from '@/components/billing/BillingContactTaxCard.vue'
import CollectionActionBanner from '@/components/billing/CollectionActionBanner.vue'
import CycleBreakdownPanel from '@/components/billing/CycleBreakdownPanel.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import EstimatedCard from '@/components/billing/EstimatedCard.vue'
import NextPaymentCard from '@/components/billing/NextPaymentCard.vue'
import PayingForCard from '@/components/billing/PayingForCard.vue'
import PayingForPanel from '@/components/billing/PayingForPanel.vue'
import PaymentMethodsCard from '@/components/billing/PaymentMethodsCard.vue'
import PaymentSchedulePanel from '@/components/billing/PaymentSchedulePanel.vue'
import StopBillingCard from '@/components/billing/StopBillingCard.vue'
import WalletCard from '@/components/billing/WalletCard.vue'
import WalletHistoryPanel from '@/components/billing/WalletHistoryPanel.vue'
import { useBillingSetup } from '@/composables/useBillingSetup'

// Billing › Overview (#69) — one scrollable surface that absorbs the legacy
// Overview, Credits, Payment methods, Subscriptions, and Settings pages. Each card
// reads from the shared useBillingOverview singleton.
//
// There is no separate onboarding page: the billing profile is filled right here
// via the "Billing contact & tax" card / EditBillingProfileDialog. Until it's
// complete we prompt the team to fill it (banner) and money-moving actions open
// the same dialog (useBillingSetup.requireSetup → setupDialogOpen).
const { complete, setupDialogOpen } = useBillingSetup()

// One docked tray at a time: the panel column is a single 24rem slot, and two
// open at once would stack two SidePanels side by side and squeeze the content
// out. A single ref names which is showing, and each card's v-model writes it.
type Tray = 'wallet' | 'cycle' | 'schedule' | 'payingFor' | null
const tray = ref<Tray>(null)

function trayModel(name: Exclude<Tray, null>) {
	return computed({
		get: () => tray.value === name,
		set: (open: boolean) => {
			tray.value = open ? name : null
		},
	})
}
const showWalletHistory = trayModel('wallet')
const showCycleBreakdown = trayModel('cycle')
const showSchedule = trayModel('schedule')
const showPayingFor = trayModel('payingFor')

// Rare, scary verbs live folded under "Advanced" — reference, not news, same
// pattern as the invoice Activity fold.
const advancedOpen = ref(false)
</script>

<template>
	<div class="flex h-full flex-col">
		<!-- Content + docked wallet-history panel (like the invoice tray): the panel
         shares the row, the content stays bright beside it — no modal overlay. -->
		<div class="flex min-h-0 flex-1">
			<div class="cards-host min-w-0 flex-1 overflow-y-auto">
				<div class="mx-auto w-full max-w-3xl space-y-5 px-6 py-8">
					<!-- Until the billing profile is filled, ask the team to complete it
               first — money-moving actions stay gated on it. -->
					<Alert
						v-if="!complete"
						theme="amber"
						title="Add your billing details"
						description="Currency, legal name, and address are needed to add credit, save a payment method, and provision servers."
						:primary-action="{ label: 'Add billing details', onClick: () => { setupDialogOpen = true } }"
					/>

					<CollectionActionBanner />
					<!-- The cycle figure is the page's headline, so it gets the full
               width; what happens to it next sits in the pair beneath. -->
					<EstimatedCard
						:active="showCycleBreakdown"
						@open="showCycleBreakdown = true"
					/>
					<div class="cards-row grid gap-4">
						<NextPaymentCard
							:active="showSchedule"
							@open="showSchedule = true"
						/>
						<WalletCard
							:active="showWalletHistory"
							@open="showWalletHistory = true"
						/>
					</div>
					<PayingForCard @open="showPayingFor = true" />
					<PaymentMethodsCard />
					<BillingContactTaxCard @edit="setupDialogOpen = true" />

					<!-- Advanced — collapsed home for the rare, destructive-adjacent
               verbs (Stop billing). -->
					<section>
						<button
							class="-mx-2 flex items-center gap-1.5 rounded-5 px-2 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							:aria-expanded="advancedOpen"
							@click="advancedOpen = !advancedOpen"
						>
							<span
								class="lucide-chevron-right size-3.5 shrink-0 text-ink-gray-5 transition-transform duration-150 ease-out"
								:class="advancedOpen ? 'rotate-90' : ''"
							/>
							<h2 class="text-base-medium text-ink-gray-8">Advanced</h2>
						</button>
						<div v-if="advancedOpen" class="mt-4">
							<StopBillingCard />
						</div>
					</section>
				</div>
			</div>

			<!-- The shared docked SidePanel owns its own slide-in/out. Only one is
           ever open (see `tray`), so they can all mount here. -->
			<WalletHistoryPanel v-model:open="showWalletHistory" />
			<CycleBreakdownPanel v-model:open="showCycleBreakdown" />
			<PaymentSchedulePanel v-model:open="showSchedule" />
			<PayingForPanel v-model:open="showPayingFor" />
		</div>

		<EditBillingProfileDialog v-model="setupDialogOpen" />
	</div>
</template>

<style scoped>
/* Queried on the content column, which is the space the page actually gets:
   it narrows when the wallet panel opens and widens when the sidebar collapses,
   so one rule covers both. (The max-w-3xl box inside can't be the container —
   it reads 768px regardless, so it never sees either change.) */
.cards-host {
	container-type: inline-size;
}
@container (min-width: 50rem) {
	.cards-row {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
}
</style>
