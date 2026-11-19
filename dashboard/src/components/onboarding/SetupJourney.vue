<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import WorldDots from '@/components/servers/WorldDots.vue'
import type { SetupStage } from '@/composables/useSiteSetup'
import { flagEmoji, hasMapCoords, project } from '@/lib/serverMap'
import type { SetupJourney } from '@/types/api'

interface SetupJourneyProps {
	journey: SetupJourney | null
	stage: SetupStage
	isDelayed: boolean
	/** The product's name. A signup without a product says "site". */
	appTitle?: string
	secondsLeft: number | null
}

const props = defineProps<SetupJourneyProps>()

// Each milestone sits in the middle of its quarter, so every label has the same room.
// The plane starts each phase at the milestone before it.
const PHASE_START: Record<SetupStage, number> = {
	booking: 0,
	server: 0.125,
	app: 0.375,
	signing: 0.625,
	arrived: 1,
	failed: 0.125,
}
const MAP_SPAN = { width: 150, height: 64 }

const MILESTONES = [
	{ at: 0.125, label: 'Queued' },
	{ at: 0.375, label: 'Provisioning' },
	{ at: 0.625, label: 'Starting' },
	{ at: 0.875, label: 'Arrived' },
]

// The plane flies towards the first milestone past its phase. After arrival there is none.
const current = computed(() =>
	MILESTONES.find((milestone) => milestone.at > PHASE_START[props.stage]),
)

const statusLine = computed(() => {
	const lines: Record<SetupStage, string> = {
		booking: 'Reserving a server',
		server: 'Starting your server',
		app: `Starting ${props.appTitle ?? 'your site'}`,
		signing: 'Signing you in',
		arrived: 'Ready',
		failed: 'Setup stopped',
	}
	return lines[props.stage]
})

const etaLine = computed(() => {
	if (['arrived', 'failed'].includes(props.stage)) return ''
	if (props.isDelayed) return 'Taking longer'
	if (props.secondsLeft === null) return ''
	return props.secondsLeft > 3
		? `About ${props.secondsLeft} s left`
		: 'Almost ready'
})

const TONES: Partial<Record<SetupStage, string>> = {
	arrived: 'text-ink-green-6',
	failed: 'text-ink-red-6',
}
const tone = computed(
	() =>
		TONES[props.stage] ??
		(props.isDelayed ? 'text-ink-amber-6' : 'text-ink-blue-6'),
)

const pin = computed(() => {
	const region = props.journey?.region
	if (!region || !hasMapCoords(region)) return null
	return project({ lat: region.latitude!, lng: region.longitude! })
})
const mapViewBox = computed(() => {
	const center = pin.value ?? { x: 440, y: 200 }
	const left = center.x - MAP_SPAN.width / 2
	const top = center.y - MAP_SPAN.height / 2
	return `${left} ${top} ${MAP_SPAN.width} ${MAP_SPAN.height}`
})

// The plane snaps to the milestone a phase starts at, then creeps towards the next one
// with time. It never reaches the next milestone until Central reports that phase.
const position = ref(PHASE_START[props.stage])
const glide = ref('700ms')
let creep: ReturnType<typeof setTimeout> | undefined

watch(
	() => props.stage,
	(stage) => {
		clearTimeout(creep)
		glide.value = '700ms'
		position.value = PHASE_START[stage]
		if (['arrived', 'failed'].includes(stage)) return
		creep = setTimeout(() => {
			glide.value = '20s'
			position.value = PHASE_START[stage] + 0.2
		}, 750)
	},
	{ immediate: true },
)
onUnmounted(() => clearTimeout(creep))

function percent(value: number): string {
	return `${value * 100}%`
}
</script>

<template>
	<section
		class="overflow-hidden rounded-6 border border-outline-gray-2 bg-surface-base"
		:class="tone"
		aria-label="Site setup progress"
	>
		<div class="relative h-24 border-b border-outline-gray-2 text-ink-gray-2">
			<svg
				class="block size-full"
				:viewBox="mapViewBox"
				preserveAspectRatio="xMidYMid slice"
				aria-hidden="true"
			>
				<WorldDots width="879" height="443" :dot="1.6" />
				<g v-if="pin" :class="tone" :transform="`translate(${pin.x} ${pin.y})`">
					<circle
						r="2.4"
						class="origin-center fill-none stroke-current [stroke-width:0.6] [transform-box:fill-box] motion-safe:animate-ping"
					/>
					<circle r="2.2" class="fill-current" />
				</g>
			</svg>
			<span
				v-if="journey?.region.title"
				class="absolute bottom-2.5 left-3 rounded-full bg-surface-base px-2 py-0.5 text-xs text-ink-gray-5 shadow-sm"
			>
				{{ flagEmoji(journey.region.country_code) }} {{ journey.region.title }}
			</span>
		</div>

		<div class="px-4 pb-4 pt-4">
			<!-- Flex drops the whitespace between the two parts of the address. -->
			<p v-if="journey?.subdomain" class="flex min-w-0 text-lg-semibold">
				<span class="text-ink-gray-9">{{ journey.subdomain }}</span>
				<span class="truncate text-ink-gray-5">.{{ journey.domain }}</span>
			</p>

			<div class="relative mt-5 h-4" aria-hidden="true">
				<span
					class="absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-surface-gray-3"
				/>
				<span
					class="absolute left-0 top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-current transition-[width] ease-out motion-reduce:transition-none"
					:style="{ width: percent(position), transitionDuration: glide }"
				/>
				<span
					class="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-current"
					style="left: 0"
				/>
				<span
					v-for="milestone in MILESTONES"
					:key="milestone.at"
					class="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-colors"
					:class="
						position >= milestone.at
							? 'bg-current'
							: 'border border-outline-gray-3 bg-surface-base'
					"
					:style="{ left: percent(milestone.at) }"
				/>
				<!-- Lucide "plane" (ISC licence), filled: the icon class only draws its outline. -->
				<svg
					v-if="stage !== 'arrived'"
					viewBox="0 0 24 24"
					class="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rotate-45 fill-current transition-[left] ease-out motion-reduce:transition-none"
					:style="{ left: percent(position), transitionDuration: glide }"
				>
					<path
						d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"
					/>
				</svg>
			</div>
			<ol class="relative mt-2 h-4 text-xs text-ink-gray-4">
				<li
					v-for="milestone in MILESTONES"
					:key="milestone.at"
					class="absolute -translate-x-1/2 whitespace-nowrap"
					:class="
						milestone === current
							? 'text-ink-gray-9'
							: position >= milestone.at
								? 'text-ink-gray-7'
								: ''
					"
					:style="{ left: percent(milestone.at) }"
				>
					{{ milestone.label }}
				</li>
			</ol>
		</div>

		<div
			class="flex items-center justify-between gap-3 border-t border-outline-gray-2 bg-surface-gray-1 px-4 py-2.5 text-sm"
		>
			<span
				class="flex min-w-0 items-center gap-2 text-ink-gray-9"
				role="status"
			>
				<span class="size-1.5 shrink-0 rounded-full bg-current" :class="tone" />
				<span class="truncate">{{ statusLine }}</span>
			</span>
			<span class="shrink-0 whitespace-nowrap tabular-nums text-ink-gray-5">
				{{ etaLine }}
			</span>
		</div>
	</section>
</template>
