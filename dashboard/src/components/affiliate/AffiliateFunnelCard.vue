<script setup lang="ts">
import { FunnelChart } from 'frappe-ui/charts'
import { computed } from 'vue'
import type { FunnelCounts } from '@/types/affiliates'

interface AffiliateFunnelCardProps {
	totals: FunnelCounts
}

const props = defineProps<AffiliateFunnelCardProps>()

const steps = computed(() => [
	{ step: 'Clicks', people: props.totals.visited },
	{ step: 'Signed up', people: props.totals.signed_up },
	{ step: 'Created a site', people: props.totals.created_site },
	{ step: 'Added billing', people: props.totals.added_billing },
	{ step: 'First invoice paid', people: props.totals.converted },
])
</script>

<template>
	<section
		class="flex flex-col gap-4 rounded-6 border border-outline-gray-1 bg-surface-base p-5"
	>
		<div class="h-80">
			<FunnelChart
				title="Conversion funnel"
				:data="steps"
				category="step"
				value="people"
			/>
		</div>
		<p class="text-p-sm text-ink-gray-5">
			Customers pay their first invoice some weeks after they sign up, so recent
			signups may still convert.
		</p>
	</section>
</template>
