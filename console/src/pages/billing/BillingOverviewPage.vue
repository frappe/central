<script setup lang="ts">
import { ref } from 'vue'
import { Button } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import CollectionActionBanner from '@/components/billing/CollectionActionBanner.vue'
import EstimatedCard from '@/components/billing/EstimatedCard.vue'
import WalletCard from '@/components/billing/WalletCard.vue'
import WalletHistoryPanel from '@/components/billing/WalletHistoryPanel.vue'
import PaymentMethodsCard from '@/components/billing/PaymentMethodsCard.vue'
import BillingContactTaxCard from '@/components/billing/BillingContactTaxCard.vue'
import SubscriptionsCard from '@/components/billing/SubscriptionsCard.vue'
import MeteredServicesCard from '@/components/billing/MeteredServicesCard.vue'
import StopBillingCard from '@/components/billing/StopBillingCard.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
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
const showWalletHistory = ref(false)
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Billing" subtitle="One account funds every server." />

    <!-- Content + docked wallet-history panel (like the invoice tray): the panel
         shares the row, the content stays bright beside it — no modal overlay. -->
    <div class="flex min-h-0 flex-1">
      <div class="min-w-0 flex-1 overflow-y-auto">
        <div class="mx-auto w-full max-w-3xl space-y-5 px-6 py-8">
          <!-- Until the billing profile is filled, ask the team to complete it
               first — money-moving actions stay gated on it. -->
          <div
            v-if="!complete"
            class="flex flex-col gap-3 rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <p class="text-p-sm text-ink-amber-7">
              Add your billing details (currency, legal name, and address) to add credit, save a
              payment method, and provision servers.
            </p>
            <Button
              variant="solid"
              theme="gray"
              label="Add billing details"
              class="shrink-0"
              @click="setupDialogOpen = true"
            />
          </div>

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

      <WalletHistoryPanel v-if="showWalletHistory" v-model="showWalletHistory" />
    </div>

    <EditBillingProfileDialog v-model="setupDialogOpen" />
  </div>
</template>
