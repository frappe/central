<script setup lang="ts">
import { Badge, Button, FormControl } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import ServerRowActions from '@/components/servers/ServerRowActions.vue'
import SiteRowActions from '@/components/servers/SiteRowActions.vue'
import type { AssetRow } from '@/composables/useServers'
import type { ServerVisual } from '@/lib/serverMap'
import type { Region } from '@/types/Central/Region'

// The "Your servers" floating card: the pill IS the panel, collapsed. Opening
// morphs it in place (see <style>). Renders both kinds indistinguishably — a site
// is a 1:1-backed VM, so it wears the same provider avatar and lists in the same
// sorted stream as a server; only its ⋯ actions differ. Presentational.
export interface ResourceRow {
	kind: 'server' | 'site'
	id: string
	name: string
	visual: ServerVisual
	specs: string
	cluster: string
	region: Region | undefined
	regionLabel: string
	flag: string
	provider: string | null
	asset?: AssetRow
	site?: { name: string; url: string | null }
}

const props = defineProps<{
	pillLabel: string
	rows: ResourceRow[]
	hasRows: boolean
	locationFilter: { ids: string[]; label: string } | null
	canOpen: boolean
	canPower: boolean
	canTerminate: boolean
	busy: string | null
	opening: string | null
}>()

defineEmits<{
	focusRow: [row: ResourceRow]
	clearLocation: []
	overview: [server: AssetRow]
	open: [server: AssetRow]
	start: [server: AssetRow]
	stop: [server: AssetRow]
	resize: [server: AssetRow]
	terminate: [server: AssetRow]
	openSite: [url: string]
	terminateSite: [name: string]
}>()

const open = defineModel<boolean>('open', { required: true })
const query = defineModel<string>('query', { required: true })
const hoverId = defineModel<string | null>('hoverId', { required: true })
</script>

<template>
	<section
		class="sp-float absolute left-4 top-4 z-30 overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-elevation-1"
		:class="open && 'sp-float-open'"
		role="region"
		aria-label="Your servers"
		@keydown.esc="open = false"
	>
		<button class="sp-float-pill text-base" :inert="open" @click="open = true">
			<span class="truncate">{{ pillLabel }}</span>
			<span class="lucide-maximize-2 size-3.5 shrink-0 text-ink-gray-6" />
		</button>

		<div class="sp-float-panel flex h-full min-h-0 flex-col" :inert="!open" :aria-hidden="!open">
			<div class="flex shrink-0 items-center justify-between gap-2 px-4 pb-2 pt-3">
				<h2 class="truncate text-base font-semibold text-ink-gray-9">{{ pillLabel }}</h2>
				<Button variant="ghost" icon="lucide-minimize-2" aria-label="Collapse list" @click="open = false" />
			</div>
			<div class="shrink-0 px-4 pb-3">
				<FormControl v-model="query" type="text" placeholder="Search" autocomplete="off" class="[&_input]:w-full">
					<template #prefix><span class="lucide-search size-4 text-ink-gray-5" /></template>
				</FormControl>
			</div>

			<div
				v-if="locationFilter"
				class="flex shrink-0 items-center justify-between gap-3 px-4 pb-2.5"
			>
				<span class="min-w-0 truncate text-sm text-ink-gray-5">
					Filtering for
					<span class="font-medium text-ink-gray-8">{{ locationFilter.label }}</span>
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
				<template v-for="(row, i) in rows" :key="row.id">
					<div
						class="sp-row group flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2.5 transition-colors"
						:style="{ animationDelay: `${Math.min(i * 25, 200)}ms` }"
						@click="$emit('focusRow', row)"
						@mouseenter="hoverId = row.id"
						@mouseleave="hoverId = null"
					>
					<span class="relative shrink-0">
						<ProviderAvatar :provider="row.provider" :size="32" />
						<span
							class="absolute -bottom-px -right-px size-2.5 rounded-full border-2 border-[var(--surface-elevation-1)]"
							:style="{ background: row.visual.dot }"
						/>
					</span>
					<span class="min-w-0 flex-1">
						<span class="flex items-center gap-1.5">
							<span class="truncate text-sm font-medium text-ink-gray-9">{{ row.name }}</span>
							<Badge
								v-if="row.visual.key !== 'active'"
								:label="row.visual.label"
								:theme="row.visual.badgeTheme"
								variant="subtle"
								size="sm"
							/>
						</span>
						<span class="block truncate text-sm text-ink-gray-5">{{ row.specs || row.regionLabel }}</span>
					</span>
					<span
						class="sp-row-actions"
						:class="{ 'sp-row-actions-active': busy === row.id || opening === row.id }"
						@click.stop
					>
						<ServerRowActions
							v-if="row.kind === 'server' && row.asset"
							:server="row.asset"
							:can-open="canOpen"
							:can-power="canPower"
							:can-terminate="canTerminate"
							:busy="busy === row.id"
							:opening="opening === row.id"
							@overview="$emit('overview', $event)"
							@open="$emit('open', $event)"
							@start="$emit('start', $event)"
							@stop="$emit('stop', $event)"
							@resize="$emit('resize', $event)"
							@terminate="$emit('terminate', $event)"
						/>
						<SiteRowActions
							v-else-if="row.site"
							:site="row.site"
							:can-open="canOpen"
							:can-terminate="canTerminate"
							:busy="busy === row.id"
							@open="$emit('openSite', $event)"
							@terminate="$emit('terminateSite', $event)"
						/>
					</span>
				</div>

				</template>

				<EmptyState
					v-if="!rows.length"
					class="m-2"
					:icon="hasRows ? 'lucide-search-x' : 'lucide-server'"
					:title="hasRows ? 'No servers match' : 'No servers yet'"
					:description="
						hasRows
							? 'Try a different search or clear the filters.'
							: 'Create your first server to host your sites.'
					"
				/>
			</div>
		</div>
	</section>
</template>

<style scoped>
/* "Your servers" morph: one floating card whose size change carries the whole
   story — the pill grows into the panel in place. The two faces crossfade inside. */
.sp-float {
	--sp-ease: cubic-bezier(0.23, 1, 0.32, 1);
	width: 10.5rem;
	height: 2rem;
	border-radius: 0.5rem;
	box-shadow: var(--shadow-sm, 0 1px 2px rgb(0 0 0 / 0.05));
	transition:
		width 180ms var(--sp-ease),
		height 180ms var(--sp-ease),
		border-radius 180ms var(--sp-ease),
		box-shadow 180ms var(--sp-ease);
}
.sp-float-open {
	width: 24rem;
	height: calc(100% - 2rem);
	border-radius: 0.75rem;
	box-shadow: var(--shadow-xl, 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1));
	transition-duration: 220ms;
}
.sp-float-pill {
	position: absolute;
	left: 0;
	top: 0;
	display: flex;
	height: 2rem;
	width: 10.5rem;
	align-items: center;
	justify-content: space-between;
	gap: 0.625rem;
	padding: 0 0.625rem;
	font-weight: 420;
	color: var(--ink-gray-7);
	transition:
		opacity 120ms ease-out,
		background-color 150ms ease;
}
.sp-float-pill:hover {
	background: var(--surface-gray-1);
}
.sp-float-open .sp-float-pill {
	opacity: 0;
}
.sp-float-panel {
	opacity: 0;
	transform: translateY(4px);
	transition:
		opacity 140ms ease-out,
		transform 220ms var(--sp-ease);
}
.sp-float-open .sp-float-panel {
	opacity: 1;
	transform: none;
	transition-delay: 40ms;
}

/* Rows cascade in as the panel opens — brief, then out of the way. */
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
	.sp-float,
	.sp-float-pill,
	.sp-float-panel {
		transition-duration: 1ms;
		transition-delay: 0ms;
	}
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
