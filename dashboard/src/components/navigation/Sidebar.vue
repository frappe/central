<script setup lang="ts">
import {
	Avatar,
	Dropdown,
	formatShortcutLabel,
	KeyboardShortcut,
	Sidebar,
	SidebarHeader,
	SidebarItem,
	SidebarLabel,
	useShortcut,
} from 'frappe-ui'
import { onScopeDispose, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import frappeCloudLogo from '@/assets/fc-logo.svg'
import { useAppMenu } from '@/composables/useAppMenu'
import { useIsMobile } from '@/composables/useIsMobile'
import { useMyProfile } from '@/composables/useMyProfile'
import { useSession } from '@/composables/useSession'
import { isMac } from '@/lib/platform'
import { sidebarSections } from './list'

const isMobile = useIsMobile()
const { activeTeamLabel } = useSession()
const { currentUser, headerMenuItems, footerMenuItems } = useAppMenu()
const { profile } = useMyProfile()

// The map pages want the full viewport, so the sidebar defaults collapsed
// there and expanded everywhere else. Only crossing that boundary re-applies
// the default — toggling by hand sticks while you stay within a section.
const route = useRoute()
const inServersSection = (path: string) => path.startsWith('/servers')
const sidebarCollapsed = ref(
	isMobile.value ? false : inServersSection(route.path),
)
watch(
	() => route.path,
	(path, previous) => {
		if (isMobile.value) return
		if (inServersSection(path) !== inServersSection(previous)) {
			sidebarCollapsed.value = inServersSection(path)
		}
	},
)

useShortcut({
	key: 'b',
	ctrl: true,
	description: 'Toggle sidebar',
	group: 'General',
	allowInInput: true,
	allowInDialog: true,
	condition: () => !isMobile.value,
	handler: () => {
		sidebarCollapsed.value = !sidebarCollapsed.value
	},
})
const sidebarShortcut = formatShortcutLabel({ key: 'b', ctrl: true })
// KeyboardShortcut's showPlus is not platform-aware. Mac reads as ⌘K;
// Windows/Linux still need the plus so Ctrl+K doesn't run together.
const showShortcutPlus = !isMac()

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
onScopeDispose(() => cancelAnimationFrame(edgeRaf))
</script>

<template>
	<Sidebar
		v-model:collapsed="sidebarCollapsed"
		:disable-collapse="isMobile"
		class="border-r"
		:class="isMobile ? '!w-full !border-r-0 bg-transparent' : ''"
	>
		<SidebarHeader
			v-if="!isMobile"
			title="Frappe Cloud"
			:subtitle="activeTeamLabel"
			:logo="frappeCloudLogo"
			:menu-items="headerMenuItems"
		/>

		<nav class="flex-1 overflow-y-auto px-2 pt-2">
			<template
				v-for="section in sidebarSections"
				:key="section.label || 'main'"
			>
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

				<template
					v-if="!section.collapsible || !collapsedSections[section.label]"
				>
					<template
						v-for="item in section.items.filter((i) => i.condition !== false)"
						:key="item.label"
					>
						<component :is="item.component" v-if="item.component" />

						<SidebarItem
							v-else
							:icon="item.icon"
							:to="item.to"
							:onclick="item.onClick"
							class="mb-0.5"
							:class="item.class"
							:active="!!item.to && item.to === route.path"
						>
							<span class="truncate text-sm">{{ item.label }}</span>
							<template v-if="item.shortcut" #suffix>
								<KeyboardShortcut
									:combo="item.shortcut"
									:show-plus="showShortcutPlus"
									class="mr-2"
								/>
							</template>
						</SidebarItem>
					</template>
				</template>
			</template>
		</nav>

		<!-- user profile dropdown -->
		<div class="mt-auto px-2 pb-2" v-if="!isMobile">
			<Dropdown
				:options="footerMenuItems"
				side="top"
				align="start"
				match-trigger-width
			>
				<template #default="{ open }">
					<!-- No transition on the button itself: `duration-*` alone animates
					     ALL properties, so the open state's white card faded in over
					     300ms and read as gray mid-fade. The collapse animation lives
					     on the inner text div, which keeps its own duration. -->
					<button
						class="flex h-10 w-full items-center rounded-4 px-1.5"
						:class="[
							sidebarCollapsed ? 'justify-center' : '',
							// z-10 lifts the open card above the menu popover's
							// downward shadow-2xl — without it the shadow paints over
							// the trigger and mutes the white card to gray. (The header
							// never needs this: its menu opens downward, casting away.)
							open
								? 'relative z-10 bg-surface-elevation-2 shadow-sm'
								: 'hover:bg-surface-gray-3',
						]"
					>
						<Avatar
							:image="profile?.user_image ?? undefined"
							:label="profile?.full_name || currentUser || ''"
							size="md"
						/>
						<!-- Name first, email beneath — the email alone reads like a
						     login prompt, not a person. -->
						<div
							class="min-w-0 flex-1 text-left duration-300 ease-in-out"
							:class="
								sidebarCollapsed
									? 'ml-0 w-0 overflow-hidden opacity-0'
									: 'ml-2 w-auto opacity-100'
							"
						>
							<div class="truncate text-sm leading-4 text-ink-gray-8">
								{{ profile?.full_name || currentUser }}
							</div>
							<div
								v-if="profile?.full_name"
								class="truncate text-xs leading-4 text-ink-gray-5"
							>
								{{ currentUser }}
							</div>
						</div>
						<!-- Single up chevron — the menu opens upward. -->
						<span
							v-if="!sidebarCollapsed"
							class="lucide-chevron-up ml-2 size-4 shrink-0 text-ink-gray-5"
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
		:aria-label="
			sidebarCollapsed
				? `Expand sidebar (${sidebarShortcut})`
				: `Collapse sidebar (${sidebarShortcut})`
		"
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
