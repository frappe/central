<script setup lang="ts">
import { type CSSProperties, computed, ref, watch } from 'vue'
import MapHoverCard from '@/components/servers/MapHoverCard.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import StatusRing from '@/components/servers/StatusRing.vue'
import WorldDots from '@/components/servers/WorldDots.vue'
import { useMapHoverCard } from '@/composables/useMapHoverCard'
import { useMapViewport } from '@/composables/useMapViewport'
import {
	computeNodes,
	type MapNode,
	type MapPin,
	type MapSpot,
	type PlusNode,
	placeHoverCard,
	project,
	type RegionSpot,
} from '@/lib/serverMap'

/**
 * The world map of a team's servers, or (picker mode) a region picker.
 * Presentational: data arrives display-ready, actions leave as emits.
 */
interface ServerMapProps {
	pins?: MapPin[]
	spots?: RegionSpot[]
	/** Picker mode: selectable region dots instead of pins and spots. */
	markers?: MapSpot[]
	/** Fleet mode: the places the map frames. Picker mode frames its markers. */
	frame?: { lat: number; lng: number }[]
	selectedId?: string | null
	/** A server hovered in the list, raised on the map. */
	highlightId?: string | null
	/** Pins whose action just finished; each plays one confirmation ring. */
	settledIds?: Set<string>
	/** Name each + spot, for a fleet with nothing else on the map. */
	labelSpots?: boolean
	interactive?: boolean
	allowCreate?: boolean
	allowOpen?: boolean
	/** Server resource id or site name opening in a new tab. */
	opening?: string | null
	compact?: boolean
}

const props = withDefaults(defineProps<ServerMapProps>(), {
	pins: () => [],
	spots: () => [],
	markers: () => [],
	frame: () => [],
	selectedId: null,
	highlightId: null,
	settledIds: () => new Set(),
	labelSpots: false,
	interactive: true,
	allowCreate: false,
	allowOpen: false,
	opening: null,
	compact: false,
})

const emit = defineEmits<{
	open: [id: string]
	'open-server': [server: NonNullable<MapPin['server']>]
	'open-site': [name: string]
	'new-server': [region: string]
	/** A cluster was clicked; the page narrows its list to these servers. */
	'cluster-open': [payload: { ids: string[]; label: string }]
	/** Picker mode: a region was chosen. */
	select: [region: string]
}>()

const element = ref<HTMLDivElement | null>(null)
const {
	width,
	height,
	scale,
	isReady,
	isResizing,
	isGliding,
	mapStyle,
	toScreen,
} = useMapViewport(
	element,
	() => (props.interactive ? props.frame : props.markers).map(project),
	// The fleet map keeps room for the filters floating over its edges.
	() => (props.interactive ? 72 : 48),
)
const { activeKey, isLocked, enter, leave, keep, lock, hide } =
	useMapHoverCard()
watch(isGliding, (value) => value && hide())

const nodes = computed<MapNode[]>(() =>
	computeNodes({
		pins: props.pins,
		spots: props.spots,
		markers: props.markers,
		selectedId: props.selectedId,
		scale: scale.value,
	}),
)

function hasMember(node: MapNode, id: string): boolean {
	if (node.type === 'server') return node.pin.id === id
	if (node.type === 'cluster') return node.members.some((m) => m.id === id)
	return node.type === 'marker' && node.marker.id === id
}

const highlightKey = computed(() => {
	const id = props.highlightId
	return id ? nodes.value.find((node) => hasMember(node, id))?.key : undefined
})

function isHot(node: MapNode): boolean {
	return node.key === activeKey.value || node.key === highlightKey.value
}

function isSettled(node: MapNode): boolean {
	return [...props.settledIds].some((id) => hasMember(node, id))
}

// A + spot that groups regions across countries has no single flag.
function getSpotFlag(node: PlusNode): string {
	const flags = new Set(node.targets.map((target) => target.flag))
	return flags.size === 1 ? node.targets[0].flag : ''
}

function getZIndex(node: MapNode): number {
	if (isHot(node)) return 30
	if (node.type === 'marker') return node.selected ? 21 : 12
	if (node.type === 'plus') return 10
	return node.type === 'cluster' ? 21 : 20
}

function getPositionStyle(node: MapNode): CSSProperties {
	const { x, y } = toScreen(node)
	return { transform: `translate3d(${x}px, ${y}px, 0)` }
}

const card = computed(() => {
	const node = nodes.value.find((each) => each.key === activeKey.value)
	if (!node) return null
	const bounds = { width: width.value, height: height.value }
	return { node, style: placeHoverCard(node, toScreen(node), bounds) }
})

// A press outside a locked card closes it. Its ⋯ menu portals out, but still counts as the card.
function onPointerDown(event: PointerEvent): void {
	if (!props.interactive || event.button !== 0 || !isLocked.value) return
	const target = event.target as Element | null
	if (!target?.closest('[data-map-card], [data-slot="content"]')) hide()
}

function clickNode(node: MapNode): void {
	if (node.type === 'marker') return emit('select', node.marker.id)
	if (node.type === 'plus') return emit('new-server', node.targets[0].id)
	if (node.type === 'cluster') {
		lock(node.key)
		emit('cluster-open', {
			ids: node.members.map((member) => member.id),
			label: node.title,
		})
		return
	}
	// A site that can't open yet has nothing behind the click, so its card stays instead.
	if (node.pin.kind === 'site' && (!props.allowOpen || !node.pin.site?.url))
		return lock(node.key)
	hide()
	emit('open', node.pin.id)
}
</script>

<template>
	<div
		ref="element"
		class="sm-tokens relative isolate h-full w-full select-none overflow-hidden bg-surface-base"
		:class="{
			'sm-animated': isReady && !isResizing,
			'sm-gliding': isGliding,
		}"
		@pointerdown="onPointerDown"
	>
		<WorldDots
			class="sm-map sm-position absolute left-0 top-0 block text-[var(--sm-dot)]"
			:style="mapStyle"
		/>

		<TransitionGroup name="smn">
			<!-- z-index rides this wrapper and the position an inner one: TransitionGroup's
			     move pass clears the transform of any child it thinks moved. -->
			<div
				v-for="node in nodes"
				:key="node.key"
				class="pointer-events-none absolute left-0 top-0"
				:style="{ zIndex: getZIndex(node) }"
			>
				<div
					class="sm-position pointer-events-auto"
					:style="getPositionStyle(node)"
				>
					<div class="sm-centre">
						<button
							v-if="node.type === 'server'"
							class="group relative block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							:aria-label="`${node.pin.name}: ${node.pin.visual.label}`"
							@click="clickNode(node)"
							@mouseenter="enter(node.key)"
							@mouseleave="leave"
						>
							<StatusRing
								class="-inset-1"
								:motion="node.pin.visual.motion"
								:color="node.pin.visual.dot"
								:is-settled="isSettled(node)"
							/>
							<span
								class="relative block rounded-full transition-transform duration-150 ease-out group-active:scale-95"
								:class="isHot(node) && 'scale-110'"
							>
								<ProviderAvatar :provider="node.pin.provider" :size="36" />
							</span>
							<span
								class="absolute bottom-0 right-0 size-3 rounded-full border-2 border-[var(--surface-base)]"
								:style="{ background: node.pin.visual.dot }"
							/>
						</button>

						<button
							v-else-if="node.type === 'cluster'"
							class="group relative block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							:aria-label="`${node.members.length} servers in ${node.title}`"
							@click="clickNode(node)"
							@mouseenter="enter(node.key)"
							@mouseleave="leave"
						>
							<span
								v-if="!node.activity"
								class="absolute -inset-2 rounded-full bg-surface-gray-3 opacity-60"
							/>
							<StatusRing
								class="-inset-2"
								:motion="node.activity?.motion ?? 'none'"
								:color="node.activity?.dot ?? ''"
								:is-settled="isSettled(node)"
							/>
							<span
								class="relative grid size-11 place-items-center rounded-full bg-[var(--sm-cluster-bg)] text-base font-semibold text-ink-gray-9 shadow-md transition-transform duration-150 ease-out group-active:scale-95"
								:class="isHot(node) && 'scale-105'"
							>
								{{ node.members.length }}
							</span>
							<span class="absolute -bottom-1 -right-1 block rounded-full">
								<ProviderAvatar :provider="node.provider" :size="20" />
							</span>
						</button>

						<button
							v-else-if="node.type === 'marker'"
							class="group relative block rounded-full outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
							:aria-label="`Region ${node.marker.regionLabel}`"
							:title="`${node.marker.flag} ${node.marker.regionLabel}`"
							@click="clickNode(node)"
						>
							<template v-if="node.selected">
								<span
									class="block size-3.5 rounded-full bg-[var(--ink-gray-9)] ring-8 ring-outline-gray-3"
								/>
								<span
									v-if="!compact"
									class="absolute left-full top-1/2 ml-6 -translate-y-1/2 whitespace-nowrap rounded-4 bg-surface-elevation-2 px-2.5 py-1.5 text-start text-sm-medium text-ink-gray-9 shadow-xl"
								>
									{{ node.marker.flag }} {{ node.marker.regionLabel }}
								</span>
							</template>
							<span
								v-else
								class="block rounded-full transition-transform duration-150 ease-out group-hover:scale-125"
								:class="
									compact
										? 'size-2 bg-[var(--ink-gray-5)]'
										: 'size-3 bg-[var(--ink-gray-9)]'
								"
							/>
						</button>

						<!-- The label sits outside the button's box, so the + stays on its coordinates. -->
						<button
							v-else
							class="group relative grid size-7 place-items-center rounded-full border border-[var(--sm-node-border)] bg-[var(--sm-node-bg)] text-[var(--sm-node-ink)] shadow-sm transition-[transform,box-shadow] duration-150 ease-out hover:shadow-md active:scale-95"
							:class="isHot(node) && 'scale-110 shadow-md'"
							:aria-label="`New server in ${node.title}`"
							@click="clickNode(node)"
							@mouseenter="enter(node.key)"
							@mouseleave="leave"
						>
							<span class="lucide-plus size-3.5" />
							<span
								v-if="labelSpots"
								class="absolute left-full top-1/2 ml-2 -translate-y-1/2 whitespace-nowrap rounded-4 bg-[var(--sm-node-bg)] px-1.5 py-0.5 text-sm text-[var(--sm-label-ink)] shadow-sm transition-opacity duration-100"
								:class="isHot(node) && 'opacity-0'"
							>
								{{ getSpotFlag(node) }} {{ node.title }}
							</span>
						</button>
					</div>
				</div>
			</div>
		</TransitionGroup>

		<Transition name="smc">
			<div
				v-if="card"
				:key="card.node.key"
				data-map-card
				class="absolute z-40 rounded-7 border border-outline-gray-1 bg-surface-elevation-1 shadow-xl"
				:class="card.node.type === 'cluster' ? 'p-2' : 'p-4'"
				:style="card.style"
				@mouseenter="keep"
				@mouseleave="leave"
				@pointerdown.capture="isLocked = true"
			>
				<MapHoverCard
					:node="card.node"
					:allow-create="allowCreate"
					:allow-open="allowOpen"
					:opening="opening"
					@open="emit('open', $event)"
					@open-server="emit('open-server', $event)"
					@open-site="emit('open-site', $event)"
					@new-server="emit('new-server', $event)"
				>
					<template #card-actions="{ pin }">
						<slot name="card-actions" :pin="pin" />
					</template>
				</MapHoverCard>
			</div>
		</Transition>
	</div>
</template>

<style scoped>
/* The dots and every node share one curve, so pins track the map through a reframe. */
.sm-position {
	will-change: transform;
}
.sm-animated .sm-position {
	transition: transform 450ms cubic-bezier(0.77, 0, 0.175, 1);
}
.sm-animated .sm-map {
	transition:
		transform 450ms cubic-bezier(0.77, 0, 0.175, 1),
		width 450ms cubic-bezier(0.77, 0, 0.175, 1),
		height 450ms cubic-bezier(0.77, 0, 0.175, 1);
}
/* A glide moves the viewport every frame itself. */
.sm-gliding .sm-position,
.sm-gliding .sm-map {
	transition: none;
}
.sm-centre {
	transform: translate(-50%, -50%);
	transition:
		transform 250ms cubic-bezier(0.23, 1, 0.32, 1),
		opacity 200ms ease-out;
}

/* Merged or split nodes scale in from something, never from nothing. */
.smn-enter-from .sm-centre {
	transform: translate(-50%, -50%) scale(0.6);
	opacity: 0;
}
.smn-leave-active {
	transition: opacity 140ms ease-in;
}
.smn-leave-to {
	opacity: 0;
}

.smc-enter-active {
	transition:
		opacity 150ms cubic-bezier(0.23, 1, 0.32, 1),
		transform 150ms cubic-bezier(0.23, 1, 0.32, 1);
}
.smc-enter-from {
	opacity: 0;
	transform: translateX(var(--smc-dx, 0px)) scale(0.97);
}
.smc-leave-active {
	transition: opacity 100ms ease-in;
}
.smc-leave-to {
	opacity: 0;
}

/* Dark mode raises each colour a step: its gray scale is compressed near the base. */
.sm-tokens {
	--sm-dot: var(--ink-gray-2);
	--sm-node-bg: var(--surface-elevation-1);
	--sm-node-border: var(--outline-gray-2);
	--sm-node-ink: var(--ink-gray-6);
	--sm-cluster-bg: var(--surface-gray-1);
	--sm-label-ink: var(--ink-gray-7);
}
[data-theme="dark"] .sm-tokens {
	--sm-dot: var(--ink-gray-3);
	--sm-node-bg: var(--surface-gray-2);
	--sm-node-border: var(--outline-gray-3);
	--sm-node-ink: var(--ink-gray-7);
	--sm-cluster-bg: var(--surface-gray-3);
	--sm-label-ink: var(--ink-gray-8);
}

@media (prefers-reduced-motion: reduce) {
	.sm-position,
	.sm-centre {
		transition: none;
	}
}
</style>
