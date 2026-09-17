<script setup lang="ts">
import { Alert, Button, Spinner } from 'frappe-ui'
import { computed, onUnmounted, ref } from 'vue'
import type { ActionStatus } from '@/types/serverCreation'

// What replaces the Create button once a request is in flight. Creation is slow and
// Central has no push channel yet, so this panel's job is to prove Central is still
// watching: the stage the request reached, and how long ago it last checked.
const props = defineProps<{
	action: ActionStatus
	regionLabel: string
	checking: boolean
	/** Automatic checking has stopped; the outcome now needs a person to ask for it. */
	stalled: boolean
	lastCheckedAt: Date | null
	checkError: string
}>()

const emit = defineEmits<{ check: []; retry: []; edit: [] }>()

const STAGES = [
	'Request accepted',
	'Sent to the region',
	'Building your server',
]
const STAGE_OF: Partial<Record<ActionStatus['status'], number>> = {
	Queued: 0,
	Dispatching: 1,
	Sent: 1,
	'In Progress': 2,
	Succeeded: 3,
}

// Failed is over. Uncertain and Timed Out are not: Atlas may hold a VM for this request,
// so the panel offers another read, never another create.
const mode = computed(() => {
	if (props.action.status === 'Failed') return 'failed'
	return props.action.status in STAGE_OF ? 'working' : 'unresolved'
})
const stage = computed(() => STAGE_OF[props.action.status] ?? 0)
const canRetry = computed(
	() => mode.value === 'failed' && !!props.action.error?.retriable,
)
const heading = computed(() => {
	if (mode.value === 'failed') return `Couldn't create ${props.action.title}`
	if (mode.value === 'unresolved') return `${props.action.title} is unconfirmed`
	return `Creating ${props.action.title}`
})
function stageLabel(index: number): string {
	return index === 1 && props.regionLabel
		? `Sent to ${props.regionLabel}`
		: STAGES[index]
}

const now = ref(Date.now())
const ticker = setInterval(() => (now.value = Date.now()), 1000)
onUnmounted(() => clearInterval(ticker))

const checkedAgo = computed(() => {
	if (!props.lastCheckedAt) return ''
	const seconds = Math.max(
		0,
		Math.round((now.value - props.lastCheckedAt.getTime()) / 1000),
	)
	if (seconds < 5) return 'Checked just now'
	if (seconds < 60) return `Checked ${seconds}s ago`
	return `Checked ${Math.round(seconds / 60)}m ago`
})
</script>

<template>
	<div class="space-y-3" role="status" aria-live="polite">
		<p class="text-base font-medium text-ink-gray-8">{{ heading }}</p>

		<ol v-if="mode === 'working'" class="space-y-2">
			<li
				v-for="(label, index) in STAGES"
				:key="label"
				class="flex items-center gap-2"
				:class="index <= stage ? 'text-ink-gray-7' : 'text-ink-gray-4'"
			>
				<span class="grid size-4 shrink-0 place-items-center">
					<span
						v-if="index < stage"
						class="lucide-check size-4 text-ink-green-3"
						aria-hidden="true"
					/>
					<Spinner v-else-if="index === stage" class="size-3.5" />
					<span
						v-else
						class="size-1.5 rounded-full bg-surface-gray-3"
						aria-hidden="true"
					/>
				</span>
				<span class="text-p-sm">{{ stageLabel(index) }}</span>
			</li>
		</ol>

		<Alert
			v-if="action.error"
			:theme="mode === 'failed' ? 'red' : 'amber'"
			:title="action.error.title"
			:description="
				[action.error.message, action.error.remediation].join(' ').trim()
			"
		/>

		<p v-if="checkError" class="text-p-sm text-ink-gray-6">{{ checkError }}</p>
		<p v-else-if="mode !== 'failed'" class="text-p-sm text-ink-gray-5">
			{{ checkedAgo }}
			<template v-if="!stalled">
				· Leave this page if you like. Creation continues.
			</template>
		</p>

		<div
			v-if="canRetry || stalled || checkError || mode === 'failed'"
			class="flex flex-wrap items-center gap-2"
		>
			<Button
				v-if="canRetry"
				variant="solid"
				icon-left="lucide-rotate-ccw"
				label="Try again"
				@click="emit('retry')"
			/>
			<Button
				v-if="mode !== 'failed' && (stalled || checkError)"
				variant="solid"
				:loading="checking"
				icon-left="lucide-refresh-cw"
				label="Check now"
				@click="emit('check')"
			/>
			<Button
				v-if="mode === 'failed'"
				:variant="canRetry ? 'ghost' : 'subtle'"
				label="Change settings"
				@click="emit('edit')"
			/>
		</div>
	</div>
</template>
