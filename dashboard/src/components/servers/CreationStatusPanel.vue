<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed, onUnmounted, ref } from 'vue'
import { getCreationStage } from '@/lib/status'
import type { ActionStatus } from '@/types/serverCreation'

// The Create button shows the stage. This panel speaks only when a person must act, and
// while the button shows, its line floats below it so the layout never moves.
const props = defineProps<{
	action: ActionStatus | null
	checking: boolean
	/** Try again is in flight. */
	retrying: boolean
	/** Automatic checking has stopped; the outcome now needs a person to ask for it. */
	stalled: boolean
	lastCheckedAt: Date | null
	checkError: string
}>()

const emit = defineEmits<{ check: []; retry: []; edit: [] }>()

// Failed is over. Uncertain and Timed Out are not: Atlas may hold a VM for this request,
// so the panel offers another read, never another create.
const mode = computed(() => {
	if (!props.action) return 'idle'
	if (props.action.status === 'Failed') return 'failed'
	return getCreationStage(props.action.status) === null
		? 'unresolved'
		: 'working'
})
// Try again re-drives this same request in Central rather than starting a new one, so
// it is offered only where another attempt could plausibly help. A failure that already
// holds a machine is never retriable, so this can never offer to build a second server.
const canRetry = computed(
	() => mode.value === 'failed' && !!props.action?.error?.retriable,
)
const failurePrimaryAction = computed(() =>
	canRetry.value
		? {
				label: 'Try again',
				loading: props.retrying,
				onClick: () => emit('retry'),
			}
		: { label: 'Change configuration', onClick: () => emit('edit') },
)
const failureSecondaryAction = computed(() =>
	canRetry.value
		? { label: 'Change configuration', onClick: () => emit('edit') }
		: undefined,
)
const failureTitle = computed(
	() => props.action?.error?.title ?? `Couldn't create ${props.action?.title}`,
)
const failureDescription = computed(() =>
	props.action?.error
		? [props.action.error.message, props.action.error.remediation]
				.join(' ')
				.trim()
		: 'Change configuration and try again.',
)
// Atlas may still build this server, so the only safe next step is to ask again.
const unresolvedDescription = computed(
	() =>
		props.action?.error?.message ??
		'The region has not confirmed this server yet. Checking again never creates a second one.',
)
const checkAction = computed(() => ({
	label: 'Check now',
	loading: props.checking,
	onClick: () => emit('check'),
}))

const isLineFloating = computed(
	() => mode.value === 'working' && !props.action?.error,
)
const canCheckInline = computed(
	() => mode.value === 'working' && (props.stalled || !!props.checkError),
)
const isLineShown = computed(
	() =>
		canCheckInline.value || (mode.value === 'unresolved' && !!checkedAgo.value),
)

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
	<div
		class="space-y-3"
		:class="{ 'mt-3': mode === 'working' && !isLineFloating }"
	>
		<Transition
			appear
			enter-active-class="transition duration-200 ease-out delay-150"
			enter-from-class="translate-y-1 opacity-0 blur-[2px]"
		>
			<Alert
				v-if="mode === 'failed'"
				theme="red"
				:title="failureTitle"
				:description="failureDescription"
				:primary-action="failurePrimaryAction"
				:secondary-action="failureSecondaryAction"
			/>
			<Alert
				v-else-if="mode === 'unresolved'"
				theme="amber"
				:title="`${action?.title} is unconfirmed`"
				:description="unresolvedDescription"
				:primary-action="checkAction"
			/>
			<Alert
				v-else-if="action?.error"
				theme="amber"
				:title="action.error.title"
				:description="failureDescription"
			/>
		</Transition>

		<Transition
			enter-active-class="transition-opacity duration-200 ease-out delay-100"
			enter-from-class="opacity-0"
		>
			<p
				v-if="isLineShown"
				class="flex items-center gap-1 text-sm text-ink-gray-5"
				:class="{ 'absolute inset-x-0 top-full mt-1.5': isLineFloating }"
			>
				<span class="min-w-0 truncate" :title="checkError || undefined">
					{{ checkError || checkedAgo || 'Checks have stopped' }}
				</span>
				<template v-if="canCheckInline">
					<span aria-hidden="true">·</span>
					<button
						type="button"
						class="shrink-0 rounded-2 font-medium text-ink-gray-8 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-outline-gray-4 disabled:text-ink-gray-5"
						:disabled="checking"
						@click="emit('check')"
					>
						{{ checking ? 'Checking' : 'Check now' }}
					</button>
				</template>
			</p>
		</Transition>
	</div>
</template>
