<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import { getCreationStage } from '@/lib/status'
import type { ActionStatus } from '@/types/serverCreation'

interface CreateServerButtonProps {
	/** A moving or succeeded request's status. Null before one exists. */
	status: ActionStatus['status'] | null
	regionLabel: string
	submitting: boolean
	disabled: boolean
}

type Tone = 'idle' | 'working' | 'success'

const props = defineProps<CreateServerButtonProps>()
const emit = defineEmits<{ create: [] }>()

const tone = computed<Tone>(() => {
	if (props.status === 'Succeeded') return 'success'
	return props.submitting || props.status ? 'working' : 'idle'
})

const label = computed(() => {
	if (tone.value === 'idle') return 'Create server'
	if (tone.value === 'success') return 'Server ready'
	const stage = props.status ? getCreationStage(props.status) : null
	if (stage === null) return 'Sending request'
	if (stage === 1 && props.regionLabel) return `Sent to ${props.regionLabel}`
	return ['Request accepted', 'Sent to the region', 'Building your server'][
		stage
	]
})

// Keyed by occurrence, so a letter both labels share glides instead of being replaced.
const letters = computed(() => {
	const seen: Record<string, number> = {}
	return [...label.value].map((letter) => {
		seen[letter] = (seen[letter] ?? 0) + 1
		return { key: `${letter}${seen[letter]}`, letter }
	})
})

// A leaving letter leaves the flow, so pin it where it stood.
function pinLeavingLetter(element: Element): void {
	const letter = element as HTMLElement
	letter.style.left = `${letter.offsetLeft}px`
	letter.style.top = `${letter.offsetTop}px`
}

function create(): void {
	if (tone.value === 'idle') emit('create')
}
</script>

<template>
	<Button
		:variant="tone === 'working' ? 'subtle' : 'solid'"
		:theme="tone === 'success' ? 'green' : 'gray'"
		size="md"
		class="create-button relative w-full"
		:data-tone="tone"
		:disabled="tone === 'idle' && disabled"
		:aria-disabled="tone !== 'idle' || undefined"
		@click="create"
	>
		<template v-if="tone === 'success'" #prefix>
			<span class="create-check lucide-check size-4.5" aria-hidden="true" />
		</template>
		<span class="sr-only">{{ label }}</span>
		<TransitionGroup
			tag="span"
			name="create-letter"
			class="create-label"
			aria-hidden="true"
			@before-leave="pinLeavingLetter"
		>
			<span
				v-for="(item, index) in letters"
				:key="item.key"
				class="create-letter"
				:style="{ '--index': index }"
				>{{ item.letter }}</span
			>
		</TransitionGroup>
	</Button>
	<span class="sr-only" role="status" aria-live="polite">
		{{ tone === 'idle' ? '' : label }}
	</span>
</template>

<style scoped>
@property --create-beam-angle {
	syntax: "<angle>";
	initial-value: 0deg;
	inherits: false;
}

.create-button {
	--ease-out: cubic-bezier(0.23, 1, 0.32, 1);
	transition:
		background-color 320ms ease-out,
		color 320ms ease-out,
		transform 160ms var(--ease-out);
}
.create-button:active {
	transform: scale(0.97);
}
.create-button:not([data-tone="idle"]) {
	pointer-events: none;
}
.create-button[data-tone="success"] {
	animation: create-success 480ms var(--ease-out);
}
@keyframes create-success {
	40% {
		transform: scale(1.03);
	}
	to {
		transform: scale(1);
	}
}

.create-button::before {
	content: "";
	position: absolute;
	inset: 0;
	padding: 1px;
	border-radius: inherit;
	background: conic-gradient(
		from var(--create-beam-angle),
		transparent 0%,
		transparent 60%,
		var(--outline-gray-4) 85%,
		transparent 100%
	);
	mask:
		linear-gradient(#000 0 0) content-box,
		linear-gradient(#000 0 0);
	mask-composite: exclude;
	opacity: 0;
	transition: opacity 240ms ease-out;
	pointer-events: none;
}
.create-button[data-tone="working"]::before {
	opacity: 1;
	animation: create-beam 1.5s linear infinite;
}
@keyframes create-beam {
	to {
		--create-beam-angle: 360deg;
	}
}

/* Button clips its label, so letters blur only lightly. */
.create-label {
	position: relative;
	display: inline-flex;
	white-space: pre;
}
.create-letter {
	display: inline-block;
}
.create-letter-move {
	transition: transform 400ms var(--ease-out);
}
.create-letter-enter-active {
	transition:
		opacity 320ms var(--ease-out),
		filter 320ms var(--ease-out),
		transform 320ms var(--ease-out);
	transition-delay: calc(min(var(--index), 24) * 8ms);
}
.create-letter-enter-from {
	opacity: 0;
	filter: blur(2px);
	transform: translateY(2px);
}
.create-letter-leave-active {
	position: absolute;
	transition:
		opacity 180ms ease-out,
		filter 180ms ease-out;
}
.create-letter-leave-to {
	opacity: 0;
	filter: blur(2px);
}

.create-check {
	animation: create-check 360ms var(--ease-out) 120ms both;
}
@keyframes create-check {
	from {
		clip-path: inset(0 100% 0 0);
	}
	to {
		clip-path: inset(0 0 0 0);
	}
}

@media (prefers-reduced-motion: reduce) {
	.create-button,
	.create-button::before,
	.create-letter-move,
	.create-letter-enter-active,
	.create-letter-leave-active {
		transition-duration: 1ms;
		transition-delay: 0ms;
	}
	.create-button:active {
		transform: none;
	}
	.create-button[data-tone="success"],
	.create-check {
		animation: none;
	}
	.create-button[data-tone="working"]::before {
		animation: none;
		background: var(--outline-gray-4);
	}
}
</style>
