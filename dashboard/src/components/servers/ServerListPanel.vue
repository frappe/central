<script setup lang="ts">
import { Badge, Button, TextInput } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import StatusRing from '@/components/servers/StatusRing.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ResourceRow } from '@/lib/serverMap'

// The servers list beside the map, always in view. Renders both kinds indistinguishably —
// a site is a 1:1-backed VM, so it wears the same provider avatar and lists in the same
// sorted stream as a server, and carries that machine's ⋯ actions. Presentational.

interface ServerListPanelProps {
	title: string
	rows: ResourceRow[]
	hasRows: boolean
	locationFilter: { ids: string[]; label: string } | null
	/** Row ids whose action just finished; each plays one confirmation ring. */
	settledIds: Set<string>
	canOpen: boolean
	canPower: boolean
	canResize: boolean
	canTerminate: boolean
	canSnapshot?: boolean
	canOpenConsole?: boolean
	canCreate: boolean
	busy: string | null
	opening: string | null
}

defineProps<ServerListPanelProps>()

defineEmits<{
	/** Row click — the page opens the resource itself (bench/site/overview). */
	openRow: [row: ResourceRow]
	clearLocation: []
	overview: [server: VirtualMachineRow]
	open: [server: VirtualMachineRow]
	pilot: [server: VirtualMachineRow]
	start: [server: VirtualMachineRow]
	stop: [server: VirtualMachineRow]
	restart: [server: VirtualMachineRow]
	resize: [server: VirtualMachineRow]
	snapshot: [server: VirtualMachineRow]
	console: [server: VirtualMachineRow]
	terminate: [server: VirtualMachineRow]
	create: []
}>()

const query = defineModel<string>('query', { required: true })
const _hoverId = defineModel<string | null>('hoverId', { required: true })
</script>

<template>
	<section class="flex min-h-0 flex-col" role="region" :aria-label="title">
		<div class="flex shrink-0 items-center gap-1.5 px-4 pb-2 pt-4">
			<h2 class="truncate text-base font-semibold text-ink-gray-9">
				{{ title }}
			</h2>
			<Badge
				class="shrink-0"
				:label="rows.length"
				theme="gray"
				variant="subtle"
				size="sm"
			/>
		</div>
		<div class="shrink-0 px-4 pb-3">
			<TextInput
				v-model="query"
				placeholder="Search by name, region or provider"
				autocomplete="off"
				class="[&_input]:w-full"
			>
				<template #prefix
					><span class="lucide-search size-4 text-ink-gray-5" /></template
				>
			</TextInput>
		</div>

		<div
			v-if="locationFilter"
			class="flex shrink-0 items-center justify-between gap-3 px-4 pb-2.5"
		>
			<span class="min-w-0 truncate text-sm text-ink-gray-5">
				Filtering for
				<span class="font-medium text-ink-gray-8"
					>{{ locationFilter.label }}</span
				>
			</span>
			<button
				class="flex shrink-0 items-center gap-1.5 text-sm text-ink-gray-6 transition-colors hover:text-ink-gray-8"
				@click="$emit('clearLocation')"
			>
				<span class="lucide-filter size-3.5" />
				Clear
			</button>
		</div>

		<div
			class="min-h-0 flex-1 overflow-y-auto border-t border-outline-alpha-gray-1 px-2 pb-2 pt-1"
		>
			<div
				v-for="(row, i) in rows"
				:key="row.id"
				class="sp-row group flex cursor-pointer items-center gap-3 rounded-6 px-2.5 py-2.5 transition-colors"
				:style="{ animationDelay: `${Math.min(i * 25, 200)}ms` }"
				@click="$emit('openRow', row)"
				@mouseenter="_hoverId = row.id"
				@mouseleave="_hoverId = null"
			>
				<span class="relative shrink-0">
					<StatusRing
						class="-inset-0.5"
						:motion="row.visual.motion"
						:color="row.visual.dot"
						:is-settled="settledIds.has(row.id)"
					/>
					<ProviderAvatar
						class="relative"
						:provider="row.provider"
						:size="32"
					/>
					<span
						class="absolute -bottom-px -right-px size-2.5 rounded-full border-2 border-[var(--surface-base)]"
						:style="{ background: row.visual.dot }"
					/>
				</span>
				<span class="min-w-0 flex-1">
					<span class="flex h-5 items-center gap-1.5">
						<span class="truncate text-sm font-medium text-ink-gray-9"
							>{{ row.name }}</span
						>
						<Badge
							v-if="row.visual.key !== 'active'"
							:label="row.visual.label"
							:theme="row.visual.badgeTheme"
							size="sm"
							class="shrink-0"
						/>
					</span>
					<span class="mt-0.5 block truncate text-sm text-ink-gray-5"
						>{{ row.specs || row.regionLabel }}</span
					>
				</span>
				<span
					class="sp-row-actions"
					:class="{ 'sp-row-actions-active': busy === row.id || opening === row.id }"
					@click.stop
				>
					<ServerRowActions
						v-if="row.server"
						:server="row.server"
						:can-open="canOpen"
						:can-power="canPower"
						:can-resize="canResize"
						:can-terminate="canTerminate"
						:can-snapshot="canSnapshot"
						:can-open-console="canOpenConsole"
						:opens-site="!!row.site"
						:busy="busy === row.server.resource_id"
						:opening="
							opening === row.server.resource_id || opening === row.site?.name
						"
						@overview="$emit('overview', $event)"
						@open="$emit('open', $event)"
						@pilot="$emit('pilot', $event)"
						@start="$emit('start', $event)"
						@stop="$emit('stop', $event)"
						@restart="$emit('restart', $event)"
						@resize="$emit('resize', $event)"
						@snapshot="$emit('snapshot', $event)"
						@console="$emit('console', $event)"
						@terminate="$emit('terminate', $event)"
					/>
				</span>
			</div>

			<EmptyState
				v-if="!rows.length"
				class="m-2"
				:icon="hasRows ? 'lucide-search-x' : 'lucide-server'"
				:title="hasRows ? 'No servers match' : 'No servers yet'"
				:description="
					hasRows
						? 'Try a different search or clear the filters.'
						: 'Create your first server to host your sites. Pick a region on the map, or start here.'
				"
			>
				<template v-if="canCreate && !hasRows" #action>
					<Button
						variant="solid"
						label="New server"
						icon-left="lucide-plus"
						@click="$emit('create')"
					/>
				</template>
			</EmptyState>
		</div>
	</section>
</template>

<style scoped>
/* Rows cascade in on first render — brief, then out of the way. */
.sp-row {
	animation: sp-row-in 250ms cubic-bezier(0.23, 1, 0.32, 1) both;
}
.sp-row:hover:not(:has(.sp-row-actions:hover)),
.sp-row:focus-within:not(:has(.sp-row-actions:focus-within)) {
	background: var(--surface-gray-2);
}
.sp-row-actions {
	display: flex;
	align-self: stretch;
	align-items: center;
	opacity: 0;
	pointer-events: none;
	transition: opacity 120ms ease-out;
}
.sp-row:hover .sp-row-actions,
.sp-row:focus-within .sp-row-actions,
.sp-row-actions-active {
	opacity: 1;
	pointer-events: auto;
}
@keyframes sp-row-in {
	from {
		opacity: 0;
		transform: translateY(6px);
	}
	to {
		opacity: 1;
		transform: translateY(0);
	}
}

@media (prefers-reduced-motion: reduce) {
	.sp-row {
		animation: none;
	}
}

@media (hover: none), (pointer: coarse) {
	.sp-row-actions {
		opacity: 1;
		pointer-events: auto;
	}
}
</style>
