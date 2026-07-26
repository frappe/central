<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useSession } from '@/composables/useSession'
import { useAppMenu } from '@/composables/useAppMenu'
import { sidebarSections } from './list'

import { Avatar, Dropdown, Sidebar, SidebarHeader, SidebarLabel, SidebarItem } from 'frappe-ui'
import frappeCloudLogo from '@/assets/fc-logo.svg'

const props = defineProps<{ isMobile?: boolean }>()

const { activeTeamLabel } = useSession()
const { currentUser, headerMenuItems, footerMenuItems } = useAppMenu()

// The map pages want the full viewport, so the sidebar defaults collapsed
// there and expanded everywhere else. Only crossing that boundary re-applies
// the default — toggling by hand sticks while you stay within a section.
const route = useRoute()
const inServersSection = (path: string) => path.startsWith('/servers')
const sidebarCollapsed = ref(props.isMobile ? false : inServersSection(route.path))
watch(
	() => route.path,
	(path, previous) => {
		if (props.isMobile) return
		if (inServersSection(path) !== inServersSection(previous)) {
			sidebarCollapsed.value = inServersSection(path)
		}
	},
)

// Composition mode has no built-in per-section collapse (that was a Legacy
// SidebarSection feature) — track collapsed labelled sections by label here.
const collapsedSections = ref<Record<string, boolean>>({})
const toggleSection = (label: string) => {
	collapsedSections.value[label] = !collapsedSections.value[label]
}

// The collapse chevron follows the cursor down the sidebar's edge strip.
// Coalesce mousemove to one update per frame — the ref only drives a CSS offset,
// so more than one write per paint is wasted work.
const edgeY = ref(60)
let pendingEdgeY = 60
let edgeRaf = 0
const onEdgeMove = (event: MouseEvent): void => {
	const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
	pendingEdgeY = event.clientY - rect.top
	if (edgeRaf) return
	edgeRaf = requestAnimationFrame(() => {
		edgeY.value = pendingEdgeY
		edgeRaf = 0
	})
}
</script>

<template>
	<Sidebar
		v-model:collapsed="sidebarCollapsed"
		:disable-collapse="isMobile"
		class="border-r"
		:class="isMobile ? '!w-full !border-r-0' : ''"
	>
		<SidebarHeader
			v-if="!isMobile"
			title="Frappe Cloud"
			:subtitle="activeTeamLabel"
			:logo="frappeCloudLogo"
			:menu-items="headerMenuItems"
		/>

		<nav class="flex-1 overflow-y-auto pt-2" :class="sidebarCollapsed ? 'px-2.5' : 'px-2'">
			<template v-for="section in sidebarSections" :key="section.label || 'main'">
				<SidebarLabel
					v-if="section.label"
					class="mt-2"
					:class="section.collapsible ? 'cursor-pointer' : ''"
					@click="section.collapsible ? toggleSection(section.label) : undefined"
				>
					{{ section.label }}
					<span
						v-if="section.collapsible"
						class="lucide-chevron-right ml-1 inline-block size-3 transition-transform"
						:class="!collapsedSections[section.label] ? 'rotate-90' : ''"
					/>
				</SidebarLabel>

				<template v-if="!section.collapsible || !collapsedSections[section.label]">
					<SidebarItem
						v-for="item in section.items.filter((i) => i.condition !== false)"
						:key="item.label"
						:icon="item.icon"
						:to="item.to"
						class="mb-0.5"
						:active="!!item.to && item.to === route.path"
					>
						<span class="truncate text-sm">{{ item.label }}</span>
					</SidebarItem>
				</template>
			</template>
		</nav>

    <!-- user profile dropdown -->
		<div class="mt-auto px-2 pb-2" v-if='!isMobile'>
			<Dropdown :options="footerMenuItems" side="top" align="start" match-trigger-width>
				<template #default="{ open }">
					<button
						class="flex h-10 w-full items-center rounded px-1.5 duration-300 ease-in-out"
						:class="[
							sidebarCollapsed ? 'justify-center' : '',
							open
								? 'bg-surface-elevation-2 shadow-sm'
								: 'hover:bg-surface-gray-3',
						]"
					>
						<Avatar :label="currentUser ?? ''" size="md" />
						<div
							class="flex-1 truncate text-left text-sm text-ink-gray-8 duration-300 ease-in-out"
							:class="
								sidebarCollapsed
									? 'ml-0 w-0 overflow-hidden opacity-0'
									: 'ml-2 w-auto opacity-100'
							"
						>
							{{ currentUser }}
						</div>
						<span
							v-if="!sidebarCollapsed"
							class="lucide-chevrons-up-down ml-2 size-4 shrink-0 text-ink-gray-5"
						/>
					</button>
				</template>
			</Dropdown>
		</div>
	</Sidebar>

	<!-- collapse knob -->
	<button
		v-if="!isMobile"
		class="sb-edge relative z-10 -mx-3 w-6 shrink-0 cursor-pointer"
		:aria-label="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
		@mousemove="onEdgeMove"
		@focus="edgeY = 60"
		@click="sidebarCollapsed = !sidebarCollapsed"
	>
		<span
			class="sb-edge-knob pointer-events-none absolute left-1/2 top-0 grid size-6 place-items-center rounded-full border border-outline-gray-2 bg-surface-elevation-1 text-ink-gray-6 shadow-sm"
			:style="{ transform: `translate(-50%, calc(${edgeY}px - 50%))` }"
		>
			<lucide-chevron-left
				class="size-3.5"
        :class='sidebarCollapsed? "rotate-180" : ""'
			/>
		</span>
	</button>
</template>

<style scoped>
/* The chevron knob is hidden until the edge is hovered or keyboard-focused;
   only opacity fades — its vertical position tracks the cursor instantly. */
.sb-edge-knob {
	opacity: 0;
	transition: opacity 150ms ease-out;
}
.sb-edge:hover .sb-edge-knob,
.sb-edge:focus-visible .sb-edge-knob {
	opacity: 1;
}
</style>
