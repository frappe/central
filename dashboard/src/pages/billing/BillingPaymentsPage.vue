<script setup lang="ts">
import BillingContactTaxCard from '@/components/billing/BillingContactTaxCard.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import PaymentMethodsCard from '@/components/billing/PaymentMethodsCard.vue'
import { useBillingSetup } from '@/composables/useBillingSetup'

const { setupDialogOpen } = useBillingSetup()
</script>

<template>
	<div class="h-full overflow-y-auto">
		<div
			class="mx-auto flex w-full max-w-3xl flex-col gap-4 p-3 md:p-4 lg:pt-8"
		>
			<PaymentMethodsCard />

			<BillingContactTaxCard @edit="setupDialogOpen = true" />
		</div>
	</div>

	<EditBillingProfileDialog v-model="setupDialogOpen" />
</template>
