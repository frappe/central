<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed, ref } from 'vue'
import BillingDetailsCard from '@/components/billing/BillingDetailsCard.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import PaymentMethodFlow from '@/components/billing/PaymentMethodFlow.vue'
import PaymentMethodsCard from '@/components/billing/PaymentMethodsCard.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'

const { complete, profile, hasLoadFailed, refresh, setupDialogOpen } =
	useBillingSetup()
const { canManageBilling } = useCapabilities()
const { reloadMethods } = useBillingOverview()

// Decided from the loaded profile, not the loading flag, which also flips on every refetch.
const needsDetails = computed(() => !!profile.value && !complete.value)
// Saves the details, then opens the add-card dialog, so setup ends with a way to pay.
const setupFlow = ref<InstanceType<typeof PaymentMethodFlow> | null>(null)
</script>

<template>
	<div class="h-full overflow-y-auto">
		<div
			class="mx-auto flex w-full max-w-3xl flex-col gap-4 p-3 md:p-4 lg:pt-8"
		>
			<Alert
				v-if="hasLoadFailed"
				theme="red"
				title="Couldn't load your billing details"
				description="You need them to add credit or a payment method. Retry, or contact support if this keeps happening."
				:primary-action="{ label: 'Retry', onClick: refresh }"
			/>
			<Alert
				v-else-if="needsDetails"
				theme="blue"
				title="Add your billing details"
				:description="
					canManageBilling
						? 'Billing details come first, then a payment method. You need both to add credit or create servers.'
						: 'Billing is not set up yet. Ask a team admin to add billing details.'
				"
				:primary-action="
					canManageBilling
						? { label: 'Add billing details', onClick: () => setupFlow?.start() }
						: undefined
				"
			/>
			<PaymentMethodsCard />
			<BillingDetailsCard
				v-if="profile && !needsDetails"
				@edit="setupDialogOpen = true"
			/>
		</div>
	</div>

	<PaymentMethodFlow ref="setupFlow" @done="reloadMethods" />
	<EditBillingProfileDialog v-model="setupDialogOpen" />
</template>
