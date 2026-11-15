<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import CopyableValue from '@/components/common/CopyableValue.vue'
import CustomerListView from '@/components/partners/CustomerListView.vue'
import EndPartnerLinkDialog from '@/components/partners/EndPartnerLinkDialog.vue'
import PayerChangeDialog, {
	type PayerChange,
} from '@/components/partners/PayerChangeDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import {
	isPartnerPaying,
	nextPayerChangeDay,
	useTeamCustomers,
} from '@/composables/usePartnerLinks'
import { useSession } from '@/composables/useSession'
import { formatDate } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { CustomerLink, PartnerLink } from '@/types/api'

const session = useSession()
const router = useRouter()
const { canManagePartners, canViewBilling } = useCapabilities()
const { customers, loading, error, reload } = useTeamCustomers()

const ending = ref<PartnerLink | null>(null)
const payerChange = ref<PayerChange | null>(null)
const rows = computed(() => customers.value?.customers ?? [])
const partnerCode = computed(() => customers.value?.partner_code ?? '')
const currency = computed(() => customers.value?.currency ?? 'INR')
const startDay = computed(() => formatDate(nextPayerChangeDay()))

function openTeam(row: CustomerLink): void {
	session.setActiveTeam(row.customer_team, '/dashboard/servers')
}

function accept(row: CustomerLink): void {
	payerChange.value = {
		link: row.name,
		payer: 'Partner',
		title: __('Pay for {0}', [row.customer_name]),
		message: __(
			"From {0}, {1}'s usage is on your monthly invoice in {2}, and its prices show in {2}.",
			[startDay.value, row.customer_name, currency.value],
		),
		confirmLabel: __('Accept'),
	}
}

function decline(row: CustomerLink): void {
	payerChange.value = {
		link: row.name,
		payer: 'Customer',
		title: __('Decline the request'),
		message: __('{0} keeps paying for its own usage.', [row.customer_name]),
		confirmLabel: __('Decline'),
		isDestructive: true,
	}
}

function stopPaying(row: CustomerLink): void {
	payerChange.value = {
		link: row.name,
		payer: 'Customer',
		title: __('Stop paying for {0}', [row.customer_name]),
		message: isPartnerPaying(row)
			? __('{0} pays for its own usage from {1}.', [
					row.customer_name,
					startDay.value,
				])
			: __('You will not start paying for {0}.', [row.customer_name]),
		confirmLabel: __('Stop paying'),
		isDestructive: true,
	}
}
</script>

<template>
	<div class="flex h-full flex-col">
		<Teleport defer to="#header-actions">
			<span v-if="partnerCode" class="flex items-center gap-2">
				<span class="text-sm text-ink-gray-5">{{ __('Partner code') }}</span>
				<CopyableValue :value="partnerCode" :label="__('Partner code')" />
			</span>
			<Button
				:label="__('Refresh')"
				icon-left="lucide-refresh-cw"
				:loading="loading"
				@click="reload"
			/>
		</Teleport>

		<div class="flex min-h-0 w-full flex-1 flex-col p-3 md:p-4">
			<CustomerListView
				:rows="rows"
				:loading="loading"
				:error="error"
				:can-manage="canManagePartners"
				:can-view-billing="canViewBilling"
				@open="openTeam"
				@view-bill="router.push('/billing')"
				@accept="accept"
				@decline="decline"
				@stop-paying="stopPaying"
				@end="ending = $event"
				@retry="reload"
			/>
		</div>

		<PayerChangeDialog v-model:target="payerChange" @changed="reload" />
		<EndPartnerLinkDialog
			v-model:target="ending"
			:other-team-name="ending?.customer_name ?? ''"
			@ended="reload"
		/>
	</div>
</template>
