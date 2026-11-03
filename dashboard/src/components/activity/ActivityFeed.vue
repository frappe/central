<script setup lang="ts">
import dayjs from 'dayjs'
import { Alert, Button, Select, Skeleton } from 'frappe-ui'
import { computed, toRef } from 'vue'
import ActivityEventRow from '@/components/activity/ActivityEventRow.vue'
import DateRangeFilter, {
	type DateRangePreset,
} from '@/components/common/DateRangeFilter.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { type ActivityScope, useActivityFeed } from '@/composables/useActivity'
import { groupActivity } from '@/lib/activity'

interface Props {
	scope: ActivityScope
	resourceId?: string
}

const props = defineProps<Props>()

const resourceId = computed(() => props.resourceId ?? null)

const {
	category,
	period,
	events,
	nextCursor,
	loading,
	loadingMore,
	error,
	reload,
	loadMore,
} = useActivityFeed(toRef(props, 'scope'), resourceId)

const SERVER_TYPES = [
	{ label: 'All types', value: '' },
	{ label: 'Actions', value: 'action' },
	{ label: 'Configuration', value: 'configuration' },
	{ label: 'Sites', value: 'site' },
	{ label: 'Access', value: 'access' },
	{ label: 'Snapshots', value: 'snapshot' },
]

const TEAM_TYPES = [
	{ label: 'All types', value: '' },
	{ label: 'Team', value: 'team' },
	{ label: 'Members', value: 'member' },
	{ label: 'Access', value: 'access' },
	{ label: 'Actions', value: 'action' },
	{ label: 'Configuration', value: 'configuration' },
	{ label: 'Sites', value: 'site' },
	{ label: 'Snapshots', value: 'snapshot' },
]

const daysAgo = (count: number): string =>
	dayjs().subtract(count, 'day').format('YYYY-MM-DD')

// Rows are kept for 12 months, so a longer preset would never show more.
const PERIOD_PRESETS: DateRangePreset[] = [
	{ label: 'Today', range: () => [daysAgo(0), daysAgo(0)] },
	{ label: 'Last 7 days', range: () => [daysAgo(6), daysAgo(0)] },
	{ label: 'Last 30 days', range: () => [daysAgo(29), daysAgo(0)] },
	{ label: 'Last 6 months', range: () => [daysAgo(182), daysAgo(0)] },
	{ label: 'Last 12 months', range: () => [daysAgo(364), daysAgo(0)] },
]

const types = computed(() =>
	props.scope === 'server' ? SERVER_TYPES : TEAM_TYPES,
)
const isFiltered = computed(() => Boolean(category.value || period.value[0]))
const months = computed(() => groupActivity(events.value))
// A server's own tab already names the server, so its name needs no link there.
const linkResource = computed(() => props.scope === 'team')

const emptyDescription = computed(() => {
	if (isFiltered.value) return 'Try another type or date range.'
	if (props.scope === 'server')
		return 'Changes to this server, its sites and its snapshots show here.'
	return 'Changes to the team, its members and its servers show here.'
})

function clearFilters() {
	category.value = ''
	period.value = []
}
</script>

<template>
	<section class="min-w-0" aria-labelledby="activity-feed-heading">
		<h2 id="activity-feed-heading" class="sr-only">Activity</h2>

		<div class="flex flex-wrap items-center gap-2 pb-3">
			<slot name="controls" />
			<Select
				v-model="category"
				class="w-40"
				:options="types"
				aria-label="Filter by type"
			/>
			<DateRangeFilter
				v-model="period"
				class="md:flex-none"
				:presets="PERIOD_PRESETS"
				any-label="Last 12 months"
			/>
		</div>

		<div
			v-if="loading && !events.length"
			class="space-y-1 pt-2"
			aria-busy="true"
		>
			<span class="sr-only">Loading activity</span>
			<Skeleton class="mb-4 h-5 w-32 rounded-4" />
			<div
				v-for="index in 6"
				:key="index"
				class="flex items-center gap-3 px-2 py-2.5"
			>
				<Skeleton class="size-7 shrink-0 rounded-full" />
				<Skeleton class="h-4 w-80 max-w-[70%] rounded-4" />
				<Skeleton class="ml-auto h-3 w-10 rounded-4" />
			</div>
		</div>

		<EmptyState
			v-else-if="error && !events.length"
			icon="lucide-cloud-off"
			title="Activity couldn't load"
			:description="error"
		>
			<template #action>
				<Button label="Retry" @click="reload" />
			</template>
		</EmptyState>

		<EmptyState
			v-else-if="!events.length"
			icon="lucide-history"
			:title="isFiltered ? 'No matching activity' : 'No activity yet'"
			:description="emptyDescription"
		>
			<template v-if="isFiltered" #action>
				<Button label="Clear filters" variant="subtle" @click="clearFilters" />
			</template>
		</EmptyState>

		<div
			v-else
			class="transition-opacity duration-150"
			:class="{ 'opacity-60': loading }"
			:aria-busy="loading"
		>
			<section
				v-for="month in months"
				:key="month.label"
				class="mt-6 first:mt-2"
			>
				<h3 class="px-3.5 pb-1.5 text-sm-medium text-ink-gray-5">
					{{ month.label }}
				</h3>

				<ol class="space-y-0.5">
					<ActivityEventRow
						v-for="cluster in month.clusters"
						:key="cluster.events[0].id"
						:events="cluster.events"
						:link-resource="linkResource"
					/>
				</ol>
			</section>

			<Alert
				v-if="error"
				theme="red"
				:title="error"
				:primary-action="{ label: 'Retry', onClick: reload }"
				class="mt-3"
			/>

			<div v-if="nextCursor" class="mt-4 px-3.5">
				<Button
					label="Load more"
					class="border border-outline-gray-2 bg-surface-gray-2 text-ink-gray-8 hover:bg-surface-gray-3 hover:text-ink-gray-9 active:bg-surface-gray-4"
					size="sm"
					:loading="loadingMore"
					@click="loadMore"
				/>
			</div>
		</div>
	</section>
</template>
