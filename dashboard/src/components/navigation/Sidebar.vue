<script setup lang="ts">
import { ref, watch, computed, h } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'
import { useSession } from '@/composables/useSession'
import { useCapabilities } from '@/composables/useCapabilities'

import { Avatar, Dropdown, Sidebar, SidebarHeader, SidebarLabel, SidebarItem } from 'frappe-ui'
import ChangeTeamDialog from '@/components/team/ChangeTeamDialog.vue'
import frappeCloudLogo from '@/assets/fc-logo.svg'

const { activeTeamLabel } = useSession()
const { canViewServers, canViewBilling, canViewServices, isMember } = useCapabilities()
const { currentUser, logout } = useAuth()
const { currentTheme, setTheme } = useTheme()

const changeTeamOpen = ref(false)

const themeOptions = [
	{ label: 'Light', icon: 'lucide-sun', value: 'light' },
	{ label: 'Dark', icon: 'lucide-moon', value: 'dark' },
	{ label: 'System', icon: 'lucide-monitor', value: 'system' },
]

// The map pages want the full viewport, so the sidebar defaults collapsed
// there and expanded everywhere else. Only crossing that boundary re-applies
// the default — toggling by hand sticks while you stay within a section.
const route = useRoute()
const inServersSection = (path: string) => path.startsWith('/servers')
const sidebarCollapsed = ref(inServersSection(route.path))
watch(
	() => route.path,
	(path, previous) => {
		if (inServersSection(path) !== inServersSection(previous)) {
			sidebarCollapsed.value = inServersSection(path)
		}
	},
)

const logoutAndRedirect = async () => {
	await logout()
	window.location.replace('/dashboard/login')
}

// No profile page exists yet — the item stays visible but inert until one does.
const profileMenuItems = [
	{ label: 'Profile', icon: 'lucide-user', disabled: true },
	{ label: 'Sign out', icon: 'lucide-log-out', onClick: logoutAndRedirect },
]

// SidebarHeader renders `menuItems` as a dropdown (title + subtitle + chevron) —
// the team switcher. The active team carries a check; the rest switch on click.
const menuItems = computed(() => [
	{
		label: 'Change team',
		icon: 'lucide-repeat',
		onClick: () => {
			changeTeamOpen.value = true
		},
	},
	{
		label: 'Theme',
		icon: 'lucide-sun-moon',
		submenu: themeOptions.map((theme) => ({
			label: theme.label,
			icon: theme.icon,
			selected: currentTheme.value === theme.value,
			onClick: () => setTheme(theme.value as 'light' | 'dark' | 'system'),
			slots: {
				suffix: ({ selected }: { selected: boolean }) =>
					selected
						? h('span', { class: 'lucide-check size-4 text-ink-gray-6' })
						: null,
			},
		})),
	},
])

const sections = computed(() => [
	{
		items: [
			{ label: 'Search', icon: 'lucide-search' },
			{ label: 'Notifications', icon: 'lucide-bell', to: '/notifications', condition: isMember.value },
		],
	},
	{
		items: [
			{ label: 'Servers', icon: 'lucide-server', to: '/servers', condition: canViewServers.value },
			{ label: 'Teams', icon: 'lucide-users', to: '/team/members', condition: isMember.value },
		],
	},
	{
		label: 'Services',
		collapsible: true,
		items: [
			{ label: 'LLM', icon: 'lucide-sparkles', to: '/services/llm', condition: canViewServices.value },
		],
	},
	{
		label: 'Billing',
		items: [
			{ label: 'Overview', icon: 'lucide-credit-card', to: '/billing', condition: canViewBilling.value },
			{ label: 'Invoices', icon: 'lucide-receipt', to: '/billing/invoices', condition: canViewBilling.value },
			{ label: 'Limit Tiers', icon: 'lucide-layers', to: '/billing/limits', condition: canViewBilling.value },
		],
	},
])

// Composition mode has no built-in per-section collapse (that was a Legacy
// SidebarSection feature) — track collapsed labelled sections by label here.
const collapsedSections = ref<Record<string, boolean>>({})
function toggleSection(label: string) {
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
	<Sidebar v-model:collapsed="sidebarCollapsed" class="border-r">
		<SidebarHeader title="Frappe Cloud" :subtitle="activeTeamLabel" :logo="frappeCloudLogo" :menu-items="menuItems" />

		<nav class="flex-1 overflow-y-auto pt-2" :class="sidebarCollapsed ? 'px-2.5' : 'px-2'">
			<template v-for="section in sections" :key="section.label || 'main'">
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
		<div class="mt-auto px-2 pb-2">
			<Dropdown :options="profileMenuItems" side="top" align="start" match-trigger-width>
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
		class="sb-edge relative -mx-3 w-6 shrink-0 cursor-pointer"
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

	<ChangeTeamDialog v-model:open="changeTeamOpen" />
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
