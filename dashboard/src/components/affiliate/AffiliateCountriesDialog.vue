<script setup lang="ts">
import { Dialog } from 'frappe-ui'
import Table from '@/components/common/Table.vue'
import { countryPlace } from '@/lib/countries'
import { flagEmoji } from '@/lib/serverMap'
import type { FunnelRow } from '@/types/affiliates'

interface AffiliateCountriesDialogProps {
	rows: FunnelRow[]
}

defineProps<AffiliateCountriesDialogProps>()
const open = defineModel<boolean>({ default: false })

const columns = [
	{ key: 'label', label: 'Country' },
	{ key: 'visited', label: 'Clicks' },
	{ key: 'signed_up', label: 'Signups' },
	{ key: 'converted', label: 'Paying' },
	{ key: 'rate', label: 'Conversion rate' },
]

const rate = (row: FunnelRow): string =>
	row.signed_up ? `${Math.round((row.converted / row.signed_up) * 100)}%` : '–'
</script>

<template>
	<Dialog v-model="open" title="All countries" size="2xl">
		<template #default>
			<Table
				:columns="columns"
				:rows="rows"
				height="flex max-h-[60vh] flex-col"
			>
				<template #label="{ row }">
					<span class="flex items-center gap-2">
						<span aria-hidden="true">
							{{ flagEmoji(countryPlace(row.label)?.code) }}
						</span>
						{{ row.label }}
					</span>
				</template>
				<template #rate="{ row }">{{ rate(row) }}</template>
			</Table>
		</template>
	</Dialog>
</template>
