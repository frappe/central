<script setup lang="ts">
import { Alert, Button, Skeleton, TabList, Tabs, TabTrigger } from 'frappe-ui'
import { computed, ref } from 'vue'
import AffiliateLinkBuilder from '@/components/affiliate/AffiliateLinkBuilder.vue'
import AffiliatePerformance from '@/components/affiliate/AffiliatePerformance.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAffiliate } from '@/composables/useAffiliate'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { openSettings } from '@/composables/useSettings'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'

const { setBreadcrumbs } = useBreadcrumbs()
setBreadcrumbs([{ label: __('Affiliate') }])

const { affiliate, cookieDays, isJoined, isPausedByFrappe, error, reload } =
	useAffiliate()

const tab = ref('performance')
// An affiliate that Frappe paused keeps its numbers but cannot make links.
const tabs = computed(() => [
	{
		value: 'performance',
		label: __('Performance'),
		iconLeft: 'lucide-chart-column-increasing',
	},
	...(isPausedByFrappe.value
		? []
		: [{ value: 'link', label: __('Make a link'), iconLeft: 'lucide-link' }]),
])
</script>

<template>
	<div class="h-full overflow-y-auto" style="scrollbar-gutter: stable">
		<!-- The gutter keeps room for the scrollbar, so a long and a short tab do not shift the page. -->
		<div class="mx-auto w-full max-w-5xl p-3 md:p-4 lg:pt-8">
			<EmptyState
				v-if="error && cookieDays === null"
				icon="lucide-cloud-off"
				:title="__('The affiliate program couldn\'t load')"
				:description="getErrorMessage(error, __('Try again in a moment.'))"
			>
				<template #action>
					<Button :label="__('Retry')" @click="reload" />
				</template>
			</EmptyState>

			<div v-else-if="cookieDays === null" class="space-y-4" aria-busy="true">
				<Skeleton class="h-10 w-64 rounded-6" />
				<Skeleton class="h-80 rounded-6" />
			</div>

			<EmptyState
				v-else-if="!affiliate || !(isJoined || isPausedByFrappe)"
				icon="lucide-megaphone"
				:title="__('Join the affiliate program')"
				:description="
					__('You get a link to share and see the signups it brings.')
				"
			>
				<template #action>
					<Button
						:label="__('Open affiliate settings')"
						@click="openSettings('affiliate')"
					/>
				</template>
			</EmptyState>

			<template v-else>
				<!-- Tabs only switches the view; the sections sit outside it, as on the server page.
				     No overflow class: a scroll box would clip the active tab's mask over the rail. -->
				<Tabs v-model="tab">
					<TabList variant="browser-tab" size="md">
						<TabTrigger
							v-for="item in tabs"
							:key="item.value"
							:value="item.value"
							:label="item.label"
							:icon-left="item.iconLeft"
						/>
					</TabList>
				</Tabs>

				<Alert
					v-if="isPausedByFrappe"
					class="mt-6"
					theme="amber"
					:title="__('Your affiliate link is paused')"
					:description="
						__(
							'New signups through it do not count while it is paused. Your earlier numbers stay here.',
						)
					"
				/>
				<AffiliatePerformance
					v-if="tab === 'performance'"
					class="mt-6"
					@make-link="tab = 'link'"
				/>
				<AffiliateLinkBuilder
					v-else-if="!isPausedByFrappe"
					class="mt-6"
					:link="affiliate.link"
				/>
			</template>
		</div>
	</div>
</template>

<style scoped>
/* Same browser-tab borders as the server page, until frappe-ui ships them. */
:deep([data-slot="tab-list"][data-variant="browser-tab"]) {
	@apply border-b-outline-gray-2;
}

:deep([data-variant="browser-tab"] [data-slot="tab-indicator"]) {
	@apply border-x-outline-gray-2 border-t-outline-gray-2;
}

/* The active tab hides the rail with a 1px strip. When text above the tabs puts the rail
   on a half pixel, the browser can round the strip one row off and the rail shows. A 3px
   strip centred on the rail covers it at any rounding. */
:deep([data-variant="browser-tab"] [data-slot="tab-indicator"]::after) {
	bottom: -3px;
	height: 3px;
}
</style>
