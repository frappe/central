<script setup lang="ts">
import { BarChart } from 'frappe-ui/charts'
import { computed } from 'vue'
import { FUNNEL_SERIES, type LinkRow } from '@/composables/useAffiliate'

interface AffiliateLinksCardProps {
	links: LinkRow[]
}

const props = defineProps<AffiliateLinksCardProps>()

const TOP = 8

// Campaigns with the most signups first; clicks break a tie.
const topCampaigns = computed(() =>
	props.links
		.filter((link) => link.visited || link.signed_up)
		.sort((a, b) => b.signed_up - a.signed_up || b.visited - a.visited)
		.slice(0, TOP),
)
</script>

<template>
	<section
		class="flex min-w-0 flex-col gap-3 rounded-6 border border-outline-gray-1 bg-surface-base p-5"
	>
		<h2 class="text-base-semibold text-ink-gray-8">Campaigns</h2>
		<p v-if="!topCampaigns.length" class="text-p-sm text-ink-gray-5">
			No visits or signups in this period.
		</p>
		<div v-else class="h-72">
			<BarChart
				:data="topCampaigns"
				x="slug"
				:y="['visited', 'signed_up', 'converted']"
				:series-config="FUNNEL_SERIES"
			/>
		</div>
	</section>
</template>
