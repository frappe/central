<script setup lang="ts">
import { ref } from "vue";
import Alert from "@/components/common/Alert.vue";
import CollectionActionBanner from "@/components/billing/CollectionActionBanner.vue";
import EstimatedCard from "@/components/billing/EstimatedCard.vue";
import WalletCard from "@/components/billing/WalletCard.vue";
import WalletHistoryPanel from "@/components/billing/WalletHistoryPanel.vue";
import PaymentMethodsCard from "@/components/billing/PaymentMethodsCard.vue";
import BillingContactTaxCard from "@/components/billing/BillingContactTaxCard.vue";
import SubscriptionsCard from "@/components/billing/SubscriptionsCard.vue";
import MeteredServicesCard from "@/components/billing/MeteredServicesCard.vue";
import StopBillingCard from "@/components/billing/StopBillingCard.vue";
import EditBillingProfileDialog from "@/components/billing/EditBillingProfileDialog.vue";
import { useBillingSetup } from "@/composables/useBillingSetup";

// Billing › Overview (#69) — one scrollable surface that absorbs the legacy
// Overview, Credits, Payment methods, Subscriptions, and Settings pages. Each card
// reads from the shared useBillingOverview singleton.
//
// There is no separate onboarding page: the billing profile is filled right here
// via the "Billing contact & tax" card / EditBillingProfileDialog. Until it's
// complete we prompt the team to fill it (banner) and money-moving actions open
// the same dialog (useBillingSetup.requireSetup → setupDialogOpen).
const { complete, setupDialogOpen } = useBillingSetup();
const showWalletHistory = ref(false);
</script>

<template>
	<div class="flex h-full flex-col">
		<!-- Content + docked wallet-history panel (like the invoice tray): the panel
         shares the row, the content stays bright beside it — no modal overlay. -->
		<div class="flex min-h-0 flex-1">
			<div class="min-w-0 flex-1 overflow-y-auto">
				<div class="mx-auto w-full max-w-3xl space-y-5 px-6 py-8">
					<!-- Until the billing profile is filled, ask the team to complete it
               first — money-moving actions stay gated on it. -->
					<Alert
						v-if="!complete"
						theme="yellow"
						title="Add your billing details"
						description="Currency, legal name, and address are needed to add credit, save a payment method, and provision servers."
						:action="{
							label: 'Add billing details',
							onClick: () => (setupDialogOpen = true),
						}"
					/>

					<CollectionActionBanner />
					<div class="grid gap-4 sm:grid-cols-2">
						<EstimatedCard />
						<WalletCard :active="showWalletHistory" @open="showWalletHistory = true" />
					</div>
					<PaymentMethodsCard />
					<BillingContactTaxCard @edit="setupDialogOpen = true" />
					<SubscriptionsCard />
					<MeteredServicesCard />
					<StopBillingCard />
				</div>
			</div>

			<!-- Stays mounted; opening/closing tweens the shell width so rapid toggles
           retarget mid-flight instead of remounting. inert when closed. -->
			<WalletHistoryPanel
				v-model="showWalletHistory"
				class="wallet-tray"
				:class="!showWalletHistory && 'wallet-tray-closed'"
				:inert="!showWalletHistory"
			/>
		</div>

		<EditBillingProfileDialog v-model="setupDialogOpen" />
	</div>
</template>

<style scoped>
/* Docked-tray reveal: the shell's width animates while the fixed-width content
   inside is clipped — no reflow mid-flight. Exit is quicker than enter. */
.wallet-tray {
	transition: width 300ms cubic-bezier(0.23, 1, 0.32, 1),
		opacity 300ms cubic-bezier(0.23, 1, 0.32, 1),
		border-color 300ms cubic-bezier(0.23, 1, 0.32, 1);
}
.wallet-tray-closed {
	width: 0 !important;
	opacity: 0;
	border-color: transparent;
	transition-duration: 200ms;
}

@media (prefers-reduced-motion: reduce) {
	.wallet-tray {
		transition: opacity 150ms ease;
	}
	.wallet-tray-closed {
		width: auto !important;
		display: none;
	}
}
</style>
