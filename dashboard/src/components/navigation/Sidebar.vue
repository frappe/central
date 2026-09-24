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
import { computed, ref, watch } from 'vue'
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
const inServersSection = (path: string) =>
	path.startsWith('/servers') &&
	!path.startsWith('/servers/snapshots') &&
	!path.startsWith('/servers/ssh-keys')
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
const toggleLabel = computed(
	() =>
		`${sidebarCollapsed.value ? 'Expand' : 'Collapse'} sidebar (${sidebarShortcut})`,
)
// KeyboardShortcut's showPlus is not platform-aware. Mac reads as ⌘K;
// Windows/Linux still need the plus so Ctrl+K doesn't run together.
const showShortcutPlus = !isMac()

// Composition mode has no built-in per-section collapse (that was a Legacy
// SidebarSection feature) — track collapsed labelled sections by label here.
const collapsedSections = ref<Record<string, boolean>>({})
const toggleSection = (label: string) => {
	collapsedSections.value[label] = !collapsedSections.value[label]
}
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

	<!-- The collapse knob sits at the middle of the sidebar edge and never moves. It shows
	     while the edge is hovered or the knob has keyboard focus. -->
	<div v-if="!isMobile" class="group relative z-10 -mx-3 w-6 shrink-0">
		<button
			class="absolute left-1/2 top-1/2 grid size-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-outline-gray-2 bg-surface-elevation-1 text-ink-gray-6 opacity-0 shadow-sm transition-opacity duration-150 hover:text-ink-gray-8 focus-visible:opacity-100 group-hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-outline-gray-3"
			:aria-label="toggleLabel"
			:title="toggleLabel"
			@click="sidebarCollapsed = !sidebarCollapsed"
		>
			<lucide-chevron-left
				class="size-3.5"
				:class="sidebarCollapsed ? 'rotate-180' : ''"
			/>
		</button>
	</div>
</template>
