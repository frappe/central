<script setup lang="ts">
import { Button, Skeleton, TabButtons } from 'frappe-ui'
import { computed, ref, toRef, watch } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import TimestampTooltip from '@/components/common/TimestampTooltip.vue'
import { useServerActivity } from '@/composables/useServerActivity'
import { formatCalendarDate, timeAgo } from '@/lib/datetime'
import { formatMemory } from '@/lib/units'
import type {
	ActivityCategory,
	ActivityDetail,
	ActivityEvent,
} from '@/types/activity'

interface Props {
	resourceId: string
}

const props = defineProps<Props>()

const {
	category,
	events,
	nextCursor,
	loading,
	loadingMore,
	error,
	reload,
	loadMore,
} = useServerActivity(toRef(props, 'resourceId'))

const FILTERS = [
	{ label: 'All', value: '' },
	{ label: 'Actions', value: 'action' },
	{ label: 'Configuration', value: 'configuration' },
	{ label: 'Sites', value: 'site' },
	{ label: 'Snapshots', value: 'snapshot' },
]

const CATEGORY_ICONS: Record<ActivityCategory, string> = {
	action: 'lucide-zap',
	configuration: 'lucide-sliders-horizontal',
	snapshot: 'lucide-camera',
	site: 'lucide-globe',
	team: 'lucide-users',
	member: 'lucide-user-plus',
	access: 'lucide-key-round',
}

// statuses the ledger writes today; an unknown one stays neutral
const STATUS_DOTS: Record<string, string> = {
	Accepted: 'bg-surface-green-7',
	Available: 'bg-surface-green-7',
	Declined: 'bg-surface-red-7',
	Deleted: 'bg-surface-gray-5',
	Expired: 'bg-surface-red-7',
	Failed: 'bg-surface-red-7',
	Pending: 'bg-surface-gray-5',
	Revoked: 'bg-surface-gray-5',
	Succeeded: 'bg-surface-green-7',
	'Timed Out': 'bg-surface-red-7',
}

const expanded = ref<Set<string>>(new Set())

// a filtered empty page still needs the tabs to get back to all
const hasActivity = ref(false)
watch(events, (rows) => {
	if (rows.length) hasActivity.value = true
})
watch(
	() => props.resourceId,
	() => {
		hasActivity.value = false
	},
)

const DETAIL_UNITS: Record<string, (value: number | string) => string> = {
	Memory: (value) => formatMemory(Number(value)),
	Size: (value) => formatMemory(Number.parseFloat(String(value))),
	Disk: (value) => `${Number(value)} GB`,
}

// the row title already names these, so the chips carry the value alone
const CHIP_VALUE_ONLY = new Set(['Snapshot', 'Size'])

const groups = computed(() => {
	const rows: { label: string; events: ActivityEvent[] }[] = []
	for (const event of events.value) {
		const label = formatCalendarDate(event.occurred_at)
		const group = rows[rows.length - 1]
		if (group?.label === label) group.events.push(event)
		else rows.push({ label, events: [event] })
	}
	return rows
})

// the preview is hidden on small screens, so every event with details can open
function canExpand(event: ActivityEvent): boolean {
	return Boolean(event.error || event.ip_address || event.details.length)
}

function toggle(id: string) {
	const open = new Set(expanded.value)
	if (open.has(id)) open.delete(id)
	else open.add(id)
	expanded.value = open
}

function showAll() {
	category.value = ''
}

function dotClass(event: ActivityEvent): string {
	return (event.status && STATUS_DOTS[event.status]) || 'bg-surface-gray-4'
}

function detailValue(label: string, value: number | string): string {
	const format = DETAIL_UNITS[label] ?? String
	return format(value)
}

interface DetailRow {
	label: string
	from: string
	to: string
}

function detailRows(details: ActivityDetail[]): DetailRow[] {
	return details.map((detail) => ({
		label: detail.label,
		from: detail.from ? detailValue(detail.label, detail.from) : '',
		to: detail.to ? detailValue(detail.label, detail.to) : '',
	}))
}

function detailId(id: string): string {
	return `activity-detail-${id}`
}

function detailText(detail: ActivityDetail): string {
	if (detail.from && detail.to) {
		const before = detailValue(detail.label, detail.from)
		const after = detailValue(detail.label, detail.to)
		return `${detail.label} ${before} → ${after}`
	}
	if (detail.to && !CHIP_VALUE_ONLY.has(detail.label)) {
		return `${detail.label} ${detailValue(detail.label, detail.to)}`
	}
	return detail.to ? detailValue(detail.label, detail.to) : detail.label
}

function detailsText(event: ActivityEvent): string {
	if (event.error) return event.error
	return event.details.slice(0, 3).map(detailText).join(' · ')
}
</script>

<template>
	<div>
		<div v-if="hasActivity" class="mb-3 overflow-x-auto py-1">
			<TabButtons v-model="category" :options="FILTERS" class="min-w-max" />
		</div>

		<div v-if="loading" class="space-y-3" aria-busy="true">
			<Skeleton v-for="index in 5" :key="index" class="h-11 rounded-4" />
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
			:title="hasActivity ? 'No activity in this category' : 'No activity yet'"
			:description="
				hasActivity
					? 'Choose another category or show all activity.'
					: 'Server changes, site changes, and snapshots will appear here.'
			"
		>
			<template v-if="hasActivity" #action>
				<Button label="Show all activity" variant="subtle" @click="showAll" />
			</template>
		</EmptyState>

		<template v-else>
			<ol>
				<li v-for="group in groups" :key="group.label" class="pb-4 last:pb-0">
					<div class="text-xs font-medium text-ink-gray-5">
						{{ group.label }}
					</div>
					<div
						class="mt-4 divide-y divide-outline-gray-1 rounded-4 border border-outline-gray-1 bg-surface-base"
					>
						<template v-for="event in group.events" :key="event.id">
							<component
								:is="canExpand(event) ? 'button' : 'div'"
								:type="canExpand(event) ? 'button' : undefined"
								class="grid h-11 w-full grid-cols-[minmax(0,1fr)_5.5rem_1rem] items-center gap-3 px-3 text-left sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_5.5rem_5.5rem_1rem] lg:grid-cols-[12rem_7rem_minmax(0,1fr)_6rem_6rem_1rem]"
								:class="
									canExpand(event)
										? 'cursor-pointer hover:bg-surface-gray-1'
										: 'cursor-default'
								"
								:aria-expanded="canExpand(event) ? expanded.has(event.id) : undefined"
								:aria-controls="canExpand(event) ? detailId(event.id) : undefined"
								@click="canExpand(event) && toggle(event.id)"
							>
								<span class="flex min-w-0 flex-col">
									<span class="flex min-w-0 items-center gap-2">
										<span
											:class="CATEGORY_ICONS[event.category]"
											class="size-4 shrink-0 text-ink-gray-5"
											aria-hidden="true"
										/>
										<span class="truncate text-sm font-medium text-ink-gray-8">
											{{ event.title }}
										</span>
										<span
											v-if="event.status"
											class="size-1.5 shrink-0 rounded-full sm:hidden"
											:class="dotClass(event)"
											aria-hidden="true"
										/>
									</span>
									<span class="truncate text-xs text-ink-gray-5 lg:hidden">
										by {{ event.actor.label }}
									</span>
								</span>
								<span class="hidden truncate text-xs text-ink-gray-5 lg:block">
									by {{ event.actor.label }}
								</span>
								<span
									class="hidden truncate text-sm sm:block"
									:class="
										event.error && !expanded.has(event.id)
											? 'text-ink-red-7'
											: 'text-ink-gray-6'
									"
								>
									{{ detailsText(event) }}
								</span>
								<span class="hidden items-center gap-1.5 sm:flex">
									<template v-if="event.status">
										<span
											class="size-1.5 shrink-0 rounded-full"
											:class="dotClass(event)"
											aria-hidden="true"
										/>
										<span
											class="min-w-0 truncate text-xs text-ink-gray-6 sm:inline"
										>
											{{ event.status }}
										</span>
									</template>
								</span>
								<span v-if="event.status" class="sr-only sm:hidden">
									{{ event.status }}
								</span>
								<span class="text-right">
									<TimestampTooltip :value="event.occurred_at">
										<span class="whitespace-nowrap text-xs text-ink-gray-5">
											{{ timeAgo(event.occurred_at) }}
										</span>
									</TimestampTooltip>
								</span>
								<span class="flex justify-center">
									<span
										v-if="canExpand(event)"
										class="lucide-chevron-right size-4 text-ink-gray-4 transition-transform"
										:class="{ 'rotate-90': expanded.has(event.id) }"
										aria-hidden="true"
									/>
								</span>
							</component>
							<div
								v-show="expanded.has(event.id)"
								:id="detailId(event.id)"
								class="pb-2 pl-9 pr-3 pt-2"
							>
								<dl class="max-w-lg space-y-1">
									<div
										v-for="row in detailRows(event.details)"
										:key="row.label"
										class="flex gap-2 text-sm"
									>
										<dt class="w-24 shrink-0 truncate text-ink-gray-6">
											{{ row.label }}
										</dt>
										<dd class="min-w-0 break-words text-ink-gray-8">
											<template v-if="row.from && row.to">
												<span class="text-ink-gray-5">{{ row.from }}</span>
												<span class="px-1 text-ink-gray-4">→</span>
												{{ row.to }}
											</template>
											<template v-else-if="row.to">{{ row.to }}</template>
											<template v-else>Updated</template>
										</dd>
									</div>
									<div v-if="event.ip_address" class="flex gap-2 text-sm">
										<dt class="w-24 shrink-0 truncate text-ink-gray-6">
											IP address
										</dt>
										<dd class="min-w-0 break-words text-ink-gray-8">
											{{ event.ip_address }}
										</dd>
									</div>
								</dl>
								<p v-if="event.error" class="max-w-lg text-sm text-ink-red-7">
									{{ event.error }}
								</p>
							</div>
						</template>
					</div>
				</li>
			</ol>

			<div
				v-if="error"
				class="mt-3 flex items-center justify-center gap-3 text-sm text-ink-red-7"
				role="alert"
			>
				<span>{{ error }}</span>
				<Button label="Retry" variant="subtle" size="sm" @click="reload" />
			</div>

			<div v-if="nextCursor" class="mt-3 flex justify-center">
				<Button label="Load more" :loading="loadingMore" @click="loadMore" />
			</div>
		</template>
	</div>
</template>
