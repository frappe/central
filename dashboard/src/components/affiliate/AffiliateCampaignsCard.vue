<script setup lang="ts">
import BillingCard from '@/components/billing/BillingCard.vue'
import Table from '@/components/common/Table.vue'
import { useAffiliate } from '@/composables/useAffiliate'
import { __ } from '@/lib/translate'
import type { AffiliateCampaign } from '@/types/affiliates'

interface AffiliateCampaignsCardProps {
	campaigns: AffiliateCampaign[]
}

defineProps<AffiliateCampaignsCardProps>()

const { sourceLabel } = useAffiliate()

const NUMBER = 'text-end tabular-nums'
const columns = [
	{ key: 'campaign', label: __('Campaign'), class: 'w-full' },
	{ key: 'source', label: __('Source') },
	{ key: 'product', label: __('Product') },
	{ key: 'signups', label: __('Signups'), class: NUMBER },
	{ key: 'paying', label: __('Paying'), class: NUMBER },
	{ key: 'to_paid', label: __('To paid'), class: NUMBER },
]

const toPaid = (row: AffiliateCampaign): string =>
	`${row.signups ? Math.round((row.paying / row.signups) * 100) : 0}%`
</script>

<template>
	<BillingCard
		:title="__('Campaigns')"
		:description="
			__('Each campaign is the name you gave a link. Sorted by paying customers.')
		"
	>
		<Table :columns="columns" :rows="campaigns" height="h-auto" flush>
			<template #campaign="{ row }">
				<span class="inline-flex items-center gap-1.5">
					<code class="font-mono text-sm text-ink-gray-8">
						{{ row.campaign ?? __('(no campaign)') }}
					</code>
					<a
						v-if="row.post_url"
						:href="row.post_url"
						target="_blank"
						rel="noopener noreferrer"
						class="text-ink-gray-5 hover:text-ink-gray-8"
						:aria-label="__('Open the post for {0}', [row.campaign ?? ''])"
					>
						<span class="lucide-external-link size-3.5" aria-hidden="true" />
					</a>
				</span>
			</template>
			<template #source="{ row }">
				{{ sourceLabel(row.source) }}
			</template>
			<template #to_paid="{ row }">
				<span class="text-ink-gray-5">{{ toPaid(row) }}</span>
			</template>
		</Table>
	</BillingCard>
</template>
