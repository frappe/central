<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { computed, ref } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import EndPartnerLinkDialog from '@/components/partners/EndPartnerLinkDialog.vue'
import { useTeamCustomers } from '@/composables/usePartnerLinks'
import { formatDate } from '@/lib/format'
import { __ } from '@/lib/translate'
import type { PartnerLink } from '@/types/api'

const { customers, loading, error, reload } = useTeamCustomers()

const query = ref(createListViewQuery({ pageSize: 20 }))
const ending = ref<PartnerLink | null>(null)
const rows = computed(() => customers.value?.customers ?? [])
const partnerCode = computed(() => customers.value?.partner_code ?? '')

const columns = computed<ListViewColumn<PartnerLink>[]>(() => [
	{ key: 'customer_name', label: __('Customer'), width: 'minmax(0,3fr)' },
	{ key: 'status', label: __('Status'), width: '7rem' },
	{
		key: 'linked_on',
		label: __('Since'),
		width: '8rem',
		value: (row) => formatDate(row.linked_on),
	},
	{ key: 'actions', label: '', width: '3rem' },
])

function actionsFor(link: PartnerLink) {
	if (link.status !== 'Active') return []
	return [
		{
			label: __('End link'),
			icon: 'lucide-unlink',
			onClick: () => (ending.value = link),
		},
	]
}
</script>

<template>
	<div class="h-full overflow-y-auto">
		<main class="mx-auto flex max-w-5xl flex-col gap-4 p-3 md:p-4 lg:mt-6">
			<div class="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h1 class="text-lg-semibold text-ink-gray-9">
						{{ __('Customers') }}
					</h1>
					<p class="mt-0.5 text-p-base text-ink-gray-5">
						{{ __('Teams that added you as their partner. Manage your customers on Frappe Connect.') }}
					</p>
				</div>
				<div v-if="partnerCode" class="flex items-center gap-2">
					<span class="text-p-sm text-ink-gray-5"
						>{{ __('Partner code') }}</span
					>
					<CopyableValue :value="partnerCode" :label="__('Partner code')" />
				</div>
			</div>

			<ListView
				v-model:query="query"
				:rows="rows"
				:columns="columns"
				:row-key="(row) => row.name"
				:loading="loading"
				:error="error"
				:empty-state="{
					title: __('No customers yet'),
					description: __('A customer adds you on Frappe Cloud with your partner code.'),
				}"
				item-label="customer"
				@retry="reload"
			>
				<template #customer_name="{ row }">
					<div class="min-w-0">
						<p class="truncate text-base-medium text-ink-gray-8">
							{{ row.customer_name }}
						</p>
						<p class="truncate text-p-sm text-ink-gray-5">
							{{ row.customer_email }}
						</p>
					</div>
				</template>
				<template #status="{ row }">
					<Badge
						:theme="row.status === 'Active' ? 'green' : 'gray'"
						:label="row.status === 'Active' ? __('Active') : __('Ended')"
					/>
				</template>
				<template #actions="{ row }">
					<RowActionsMenu
						:options="actionsFor(row)"
						:label="__('Customer actions')"
					/>
				</template>
			</ListView>
		</main>

		<EndPartnerLinkDialog
			v-model:target="ending"
			:other-team-name="ending?.customer_name ?? ''"
			@ended="reload"
		/>
	</div>
</template>
