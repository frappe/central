<script setup lang="ts">
import { Badge, Button } from 'frappe-ui'
import { computed } from 'vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import type { MapNode, MapPin } from '@/lib/serverMap'

// The map's hover card, split out of ServerMap so the map component keeps just
// the pan/zoom viewport. Purely presentational: ServerMap owns placement (the
// wrapping positioned box); this renders the content for whichever node kind is
// showing and forwards every action as an emit (plus the card-actions slot for a
// server's ⋯ menu). Markers never open a card, so only server/cluster/plus reach here.
const props = defineProps<{
	node: MapNode
	/** Show create affordances inside cards (page gates on server:create). */
	allowCreate: boolean
	/** Show direct bench-open affordances inside cluster cards. */
	allowOpen: boolean
	/** Server resource id or site name currently opening in a new tab. */
	opening: string | null
}>()

const emit = defineEmits<{
	open: [id: string]
	'open-server': [server: NonNullable<MapPin['server']>]
	'open-site': [name: string]
	'new-server': [region: string]
}>()

const hasManyTargets = computed(
	() => props.node.type === 'plus' && props.node.targets.length > 1,
)

function canOpenBench(server: NonNullable<MapPin['server']>): boolean {
	return props.allowOpen && server.status === 'Running' && !!server.gateway_url
}
</script>

<template>
	<!-- Single VM (server or site): real mirror fields only. The IP/Plan/Version
	     rows are server-only and simply don't render for a site (fields absent). -->
	<template v-if="node.type === 'server'">
		<div class="flex items-start gap-2">
			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-2">
					<span class="truncate text-base font-semibold text-ink-gray-9"
						>{{ node.pin.name }}</span
					>
					<Badge
						:theme="node.pin.visual.badgeTheme"
						size="sm"
						:label="node.pin.visual.label"
					/>
				</div>
				<div
					v-if="node.pin.specs"
					class="mt-0.5 truncate text-sm text-ink-gray-5"
				>
					{{ node.pin.specs }}
				</div>
			</div>
			<div class="-mr-1.5 -mt-1" @click.stop>
				<slot name="card-actions" :pin="node.pin" />
			</div>
		</div>
		<div class="mt-3 flex items-baseline justify-between gap-3 text-sm">
			<span class="shrink-0 font-medium text-ink-gray-8">Region</span>
			<span class="truncate text-ink-gray-9"
				>{{ node.pin.flag }} {{ node.pin.regionLabel }}</span
			>
		</div>
		<div
			v-if="node.pin.publicIpv4"
			class="mt-2 flex items-baseline justify-between gap-3 text-sm"
		>
			<span class="shrink-0 font-medium text-ink-gray-8">IP</span>
			<span class="truncate font-mono text-[13px] text-ink-gray-9"
				>{{ node.pin.publicIpv4 }}</span
			>
		</div>
		<div
			v-if="node.pin.plan"
			class="mt-2 flex items-baseline justify-between gap-3 text-sm"
		>
			<span class="shrink-0 font-medium text-ink-gray-8">Plan</span>
			<span class="truncate text-ink-gray-9">{{ node.pin.plan }}</span>
		</div>
		<div
			v-if="node.pin.frappeVersion"
			class="mt-2 flex items-baseline justify-between gap-3 text-sm"
		>
			<span class="shrink-0 font-medium text-ink-gray-8">Version</span>
			<span class="truncate text-ink-gray-9">{{ node.pin.frappeVersion }}</span>
		</div>
	</template>

	<!-- Cluster: the servers at this spot -->
	<template v-else-if="node.type === 'cluster'">
		<div class="flex items-center justify-between gap-2 px-1.5 pb-1 pt-0.5">
			<span class="min-w-0 truncate text-xs font-medium text-ink-gray-5">
				{{ node.members[0].flag }} {{ node.title }} ·
				{{ node.members.length }}
				servers
			</span>
			<button
				v-if="allowCreate"
				class="grid size-5 shrink-0 place-items-center rounded-5 text-ink-gray-6 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8 active:scale-95"
				:title="`New server in ${node.title}`"
				:aria-label="`New server in ${node.title}`"
				@click="emit('new-server', node.members[0].cluster)"
			>
				<span class="lucide-plus size-3.5" />
			</button>
		</div>
		<div
			v-for="m in node.members"
			:key="m.id"
			class="group flex w-full items-center gap-2.5 rounded-6 p-1.5 transition-colors hover:bg-surface-gray-2"
		>
			<button
				class="flex min-w-0 flex-1 items-center gap-2.5 text-left"
				@click="emit('open', m.id)"
			>
				<span class="relative shrink-0">
					<ProviderAvatar :provider="m.provider" :size="28" />
					<span
						class="absolute -bottom-px -right-px size-2.5 rounded-full border-2 border-[var(--surface-elevation-1)]"
						:style="{ background: m.visual.dot }"
					/>
				</span>
				<span class="min-w-0 flex-1">
					<span class="block truncate text-sm font-medium text-ink-gray-8"
						>{{ m.name }}</span
					>
					<span class="mt-0.5 block truncate text-xs text-ink-gray-5"
						>{{ m.specs }}</span
					>
				</span>
			</button>
			<!-- Server: open bench. Site: open its live URL. Same slot, per kind. -->
			<button
				v-if="m.kind === 'server' && m.server"
				class="grid size-7 shrink-0 place-items-center rounded-4 text-ink-gray-5 transition-opacity disabled:cursor-default disabled:opacity-30 enabled:opacity-0 enabled:hover:text-ink-gray-8 group-hover:enabled:opacity-100"
				:class="{ '!opacity-100': opening === m.server.resource_id }"
				:disabled="!canOpenBench(m.server) || opening === m.server.resource_id"
				title="Open"
				aria-label="Open"
				@click.stop="emit('open-server', m.server)"
			>
				<span
					:class="opening === m.server.resource_id ? 'lucide-loader-circle size-3.5 animate-spin' : 'lucide-arrow-up-right size-3.5'"
				/>
			</button>
			<button
				v-else-if="m.site"
				class="grid size-7 shrink-0 place-items-center rounded-4 text-ink-gray-5 transition-opacity disabled:cursor-default disabled:opacity-30 enabled:opacity-0 enabled:hover:text-ink-gray-8 group-hover:enabled:opacity-100"
				:class="{ '!opacity-100': opening === m.site.name }"
				:disabled="
					!allowOpen ||
					!m.site.url ||
					m.server?.status !== 'Running' ||
					opening === m.site.name
				"
				title="Open"
				aria-label="Open"
				@click.stop="m.site.url && emit('open-site', m.site.name)"
			>
				<span
					:class="opening === m.site.name ? 'lucide-loader-circle size-3.5 animate-spin' : 'lucide-arrow-up-right size-3.5'"
				/>
			</button>
		</div>
	</template>

	<!-- Empty region: what is offered here, and a direct path to create (markers never open cards).
	     One region: the button creates. Several: each row creates in its own region. -->
	<template v-else-if="node.type === 'plus'">
		<div class="truncate text-base font-semibold text-ink-gray-9">
			{{ node.targets.length === 1 ? node.targets[0].flag : '' }}
			{{ node.title }}
		</div>
		<div class="mt-0.5 text-sm text-ink-gray-5">No servers here yet</div>

		<div class="-mx-1.5 mt-3 space-y-0.5">
			<component
				:is="hasManyTargets ? 'button' : 'div'"
				v-for="target in node.targets"
				:key="target.id"
				class="group flex w-full items-center gap-2.5 rounded-6 p-1.5 text-left"
				:class="hasManyTargets && 'transition-colors enabled:hover:bg-surface-gray-2 disabled:cursor-not-allowed'"
				:disabled="hasManyTargets ? !target.isReachable : undefined"
				:aria-label="hasManyTargets ? `New server in ${target.regionLabel}` : undefined"
				@click="hasManyTargets && emit('new-server', target.id)"
			>
				<ProviderAvatar :provider="target.provider" :size="24" />
				<span class="min-w-0 flex-1">
					<span class="block truncate text-sm font-medium text-ink-gray-8">
						{{ target.provider || target.regionLabel }}
					</span>
					<span
						class="mt-0.5 block truncate text-xs"
						:class="target.isReachable ? 'text-ink-gray-5' : 'text-ink-amber-6'"
					>
						{{ target.isReachable
							? hasManyTargets ? target.regionLabel : 'Available now'
							: 'Unreachable right now' }}
					</span>
				</span>
				<span
					v-if="hasManyTargets && target.isReachable"
					class="lucide-plus size-3.5 shrink-0 text-ink-gray-5 opacity-0 transition-opacity group-hover:opacity-100"
				/>
			</component>
		</div>

		<Button
			v-if="!hasManyTargets"
			class="mt-3 w-full"
			variant="solid"
			label="New server"
			icon-left="lucide-plus"
			:disabled="!node.targets[0].isReachable"
			@click="emit('new-server', node.targets[0].id)"
		/>
	</template>
</template>
