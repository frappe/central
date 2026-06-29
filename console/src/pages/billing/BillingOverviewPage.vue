<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import CollectionActionBanner from '@/components/billing/CollectionActionBanner.vue'
import EstimatedCard from '@/components/billing/EstimatedCard.vue'
import WalletCard from '@/components/billing/WalletCard.vue'
import PaymentMethodsCard from '@/components/billing/PaymentMethodsCard.vue'
import BillingContactTaxCard from '@/components/billing/BillingContactTaxCard.vue'
import SubscriptionsCard from '@/components/billing/SubscriptionsCard.vue'
import StopBillingCard from '@/components/billing/StopBillingCard.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'

// Billing › Overview (#69) — one scrollable surface that absorbs the legacy
// Overview, Credits, Payment methods, Subscriptions, and Settings pages. Each card
// reads from the shared useBillingOverview singleton; the profile-edit dialog is
// owned here so the Contact and Tax cards share one instance.
const showEditProfile = ref(false)
</script>

<template>
  <div class="flex h-full flex-col">
    <PageHeader title="Billing" />

    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="mx-auto w-full max-w-4xl space-y-5 px-5 py-6">
        <CollectionActionBanner />
        <EstimatedCard />
        <WalletCard />
        <PaymentMethodsCard />
        <BillingContactTaxCard @edit="showEditProfile = true" />
        <SubscriptionsCard />
        <StopBillingCard />
      </div>
    </div>

    <EditBillingProfileDialog v-model="showEditProfile" />
  </div>
</template>
