<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import ActivityActorAvatar from '@/components/activity/ActivityActorAvatar.vue'
import ActivityDetailValue from '@/components/activity/ActivityDetailValue.vue'
import ActivityResourceName from '@/components/activity/ActivityResourceName.vue'
import ActivitySummary from '@/components/activity/ActivitySummary.vue'
import TimestampTooltip from '@/components/common/TimestampTooltip.vue'
import {
	getEventIcon,
	getEventSummary,
	getSentenceParts,
	getStatusTheme,
	getSummaryDetails,
} from '@/lib/activity'
import { timeAgo } from '@/lib/datetime'
import type { ActivityEvent } from '@/types/activity'

interface Props {
	/** One event, or back-to-back repeats of it, newest first. */
	events: ActivityEvent[]
	/** Links a server name to its page; off on that server's own tab. */
	linkResource?: boolean
}

const props = withDefaults(defineProps<Props>(), { linkResource: false })

const RUN_PAGE = 5

const isOpen = ref(false)
const runLimit = ref(RUN_PAGE)
const event = computed(() => props.events[0])
const isRun = computed(() => props.events.length > 1)
const repeatCount = computed(() =>
	props.events.length === 2 ? 'twice' : `${props.events.length} times`,
)
const detailId = computed(() => `activity-detail-${event.value.id}`)
const parts = computed(() => getSentenceParts(event.value))
const summary = computed(() => getEventSummary(event.value))
const filteredDetails = computed(() => getSummaryDetails(event.value))
const changeCount = computed(() => filteredDetails.value.length)
const hasMultipleChanges = computed(() => !isRun.value && changeCount.value > 1)

const statusTheme = computed(() =>
	event.value.status ? getStatusTheme(event.value.status) : 'gray',
)
// Success is the normal outcome, so only a status that needs attention earns a badge.
// An error line already says it failed, so the badge would only repeat it.
const showStatus = computed(
	() =>
		!event.value.error &&
		(statusTheme.value === 'red' || statusTheme.value === 'amber'),
)
const isFailed = computed(
	() => Boolean(event.value.error) || statusTheme.value === 'red',
)

// A single change detail fits inline on line 1; expanding would only repeat it.
// Open as an accordion only when several items or several repeats exist.
const canExpand = computed(() => isRun.value || changeCount.value > 1)

const visibleRun = computed(() => props.events.slice(0, runLimit.value))
const hiddenCount = computed(() => props.events.length - runLimit.value)

function toggle() {
	if (canExpand.value) isOpen.value = !isOpen.value
}
</script>

<template>
	<li class="relative">
		<div
			class="group flex items-start gap-3.5 rounded-6 px-3.5 py-3 transition-colors duration-150 sm:py-3.5"
			:class="{
				'cursor-pointer hover:bg-surface-gray-1/40': canExpand,
				'bg-surface-gray-1/40': isOpen,
			}"
			@click="toggle"
		>
			<div class="shrink-0 pt-0.5">
				<ActivityActorAvatar
					:actor="event.actor"
					:icon="getEventIcon(event)"
					:failed="isFailed"
				/>
			</div>

			<div class="min-w-0 flex-1">
				<p class="text-base text-ink-gray-6">
					<template v-for="(part, index) in parts" :key="index">
						<span
							v-if="part.role === 'actor'"
							class="text-base-medium text-ink-gray-9"
						>
							{{ part.text }}
						</span>
						<ActivityResourceName
							v-else-if="part.role === 'resource'"
							:resource="event.resource"
							:link="linkResource"
						/>
						<template v-else>{{ part.text }}</template>
					</template>
					<template v-if="isRun">
						<span class="text-ink-gray-5"> · {{ repeatCount }}</span>
					</template>
					<template v-else-if="hasMultipleChanges">
						<span class="text-ink-gray-5"> · {{ changeCount }} changes</span>
					</template>
					<template v-else-if="summary.length">
						<span class="text-ink-gray-4" aria-hidden="true"> · </span>
						<ActivitySummary :parts="summary" />
					</template>
				</p>

				<!-- 2nd line: relative date with hover tooltip, plus status or error -->
				<div
					class="mt-0.5 flex flex-wrap items-center gap-x-2 text-p-sm text-ink-gray-5"
				>
					<TimestampTooltip :value="event.occurred_at">
						<span class="cursor-default hover:text-ink-gray-7">
							{{ timeAgo(event.occurred_at) }}
						</span>
					</TimestampTooltip>
					<template v-if="showStatus">
						<span class="text-ink-gray-4" aria-hidden="true">·</span>
						<span
							class="font-medium"
							:class="statusTheme === 'red' ? 'text-ink-red-6' : 'text-ink-amber-6'"
						>
							{{ event.status }}
						</span>
					</template>
					<template v-if="event.error">
						<span class="text-ink-gray-4" aria-hidden="true">·</span>
						<span class="font-medium text-ink-red-6">{{ event.error }}</span>
					</template>
				</div>
			</div>

			<div v-if="canExpand" class="shrink-0 pt-1">
				<button
					type="button"
					class="flex size-6 items-center justify-center rounded-4 text-ink-gray-4 transition-colors hover:text-ink-gray-7 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
					:aria-expanded="isOpen"
					:aria-controls="detailId"
					:aria-label="isOpen ? 'Hide details' : 'Show details'"
					@click.stop="toggle"
				>
					<span
						class="lucide-chevron-down size-4 transition-transform duration-150"
						:class="{ 'rotate-180': isOpen }"
						aria-hidden="true"
					/>
				</button>
			</div>
		</div>

		<!-- Expanded sublist: no bg, light border compatible with light & dark mode, clean columns, hoverable items showing time tooltip -->
		<div
			v-if="canExpand"
			v-show="isOpen"
			:id="detailId"
			class="mb-3 ml-11 mt-1 rounded-6 border border-outline-gray-1 p-2 text-p-sm sm:p-2.5"
		>
			<!-- One event: each change on its own line -->
			<ul v-if="!isRun && filteredDetails.length" class="space-y-0.5">
				<li
					v-for="(detail, index) in filteredDetails"
					:key="`${detail.label}-${index}`"
					class="flex items-baseline gap-4 rounded-4 px-2 py-1.5 hover:bg-surface-gray-1"
				>
					<span
						class="w-44 shrink-0 truncate text-ink-gray-5"
						:title="detail.label"
					>
						{{ detail.label }}
					</span>
					<ActivityDetailValue :detail="detail" />
				</li>
			</ul>

			<p v-if="!isRun && event.error" class="mt-2 text-p-sm text-ink-red-6">
				{{ event.error }}
			</p>

			<!-- A run of one event: each occurrence on its own line, newest first -->
			<template v-if="isRun">
				<ul class="space-y-0.5">
					<li
						v-for="occurrence in visibleRun"
						:key="occurrence.id"
						class="flex items-baseline gap-4 rounded-4 px-2 py-1.5 hover:bg-surface-gray-1"
					>
						<TimestampTooltip
							:value="occurrence.occurred_at"
							trigger-class="w-28 shrink-0"
							align="start"
						>
							<span class="whitespace-nowrap text-ink-gray-5">
								{{ timeAgo(occurrence.occurred_at) }}
							</span>
						</TimestampTooltip>
						<span v-if="occurrence.error" class="text-ink-red-6">
							{{ occurrence.error }}
						</span>
						<span v-else class="flex min-w-0 flex-wrap gap-x-4 gap-y-0.5">
							<span
								v-for="(detail, index) in getSummaryDetails(occurrence)"
								:key="`${detail.label}-${index}`"
								class="inline-flex min-w-0 items-baseline gap-1.5"
							>
								<span class="text-ink-gray-5">{{ detail.label }}</span>
								<ActivityDetailValue :detail="detail" />
							</span>
						</span>
					</li>
				</ul>

				<div
					v-if="hiddenCount > 0"
					class="mt-2.5 flex items-center gap-3 border-t border-outline-gray-1 px-2 pt-2"
				>
					<Button
						variant="subtle"
						size="sm"
						:label="`Show ${Math.min(hiddenCount, 10)} more`"
						@click.stop="runLimit += 10"
					/>
					<span class="text-xs text-ink-gray-5">
						Showing {{ visibleRun.length }} of {{ events.length }} events
					</span>
				</div>
			</template>
		</div>
	</li>
</template>
