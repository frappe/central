import type { Component } from 'vue'
import { defineAsyncComponent, ref } from 'vue'
import { MOBILE_BREAKPOINT } from '@/composables/useIsMobile'
import { router } from '@/router'

// Forms load on demand. Async also keeps this module free of an import cycle:
// TeamForm calls closeSettings from here.
const ProfileForm = defineAsyncComponent(
	() => import('@/components/settings/forms/ProfileForm.vue'),
)
const NotificationsForm = defineAsyncComponent(
	() => import('@/components/settings/forms/NotificationsForm.vue'),
)
const AppearanceForm = defineAsyncComponent(
	() => import('@/components/settings/forms/AppearanceForm.vue'),
)
const TeamsForm = defineAsyncComponent(
	() => import('@/components/settings/forms/TeamsForm.vue'),
)
const TeamForm = defineAsyncComponent(
	() => import('@/components/settings/forms/TeamForm.vue'),
)

// One settings surface for everything that used to be its own modal: your
// profile, your notification delivery, the theme, your teams, and the active
// team's settings. Callers name the tab they want and this decides how to show
// it — a dialog on desktop, a real page on mobile, where a modal over a 375px
// screen is just a page with the edges shaved off.
export type SettingsTab =
	| 'profile'
	| 'notifications'
	| 'appearance'
	| 'teams'
	| 'team'

export interface SettingsTabDef {
	value: SettingsTab
	/** Which section of the sidebar the entry sits in. */
	group: 'Account' | 'Team'
	/** Sidebar entry and mobile row label. */
	label: string
	/** Lucide class for the entry; the profile tab uses your avatar instead. */
	icon: string
	/** Panel/page heading. Matches the label unless brevity needs them to differ. */
	title: string
	description?: string
	component: Component
	/**
	 * Capability gate, resolved by the consumer against useCapabilities:
	 * 'member' needs any standing on the team, 'teamAdmin' needs team:edit or
	 * team:delete. Undefined is always available.
	 */
	requires?: 'member' | 'teamAdmin'
}

export const SETTINGS_TABS: SettingsTabDef[] = [
	{
		value: 'profile',
		group: 'Account',
		label: 'My profile',
		icon: 'lucide-user',
		title: 'My profile',
		description: 'How you appear to everyone you share a team with.',
		component: ProfileForm,
	},
	{
		value: 'notifications',
		group: 'Account',
		label: 'Notifications',
		icon: 'lucide-bell',
		title: 'Notifications',
		description:
			'Choose how each kind of notification reaches you. These apply to your account on this team only.',
		component: NotificationsForm,
		requires: 'member',
	},
	{
		value: 'appearance',
		group: 'Account',
		label: 'Appearance',
		icon: 'lucide-sun-moon',
		title: 'Appearance',
		description: 'How the console looks.',
		component: AppearanceForm,
	},
	{
		value: 'teams',
		group: 'Team',
		label: 'Your teams',
		icon: 'lucide-users',
		title: 'Your teams',
		description: 'Switch between the teams you belong to, or start a new one.',
		component: TeamsForm,
	},
	{
		value: 'team',
		group: 'Team',
		label: 'Team settings',
		icon: 'lucide-building-2',
		title: 'Team settings',
		description: 'Settings for the team you are working in.',
		component: TeamForm,
		requires: 'teamAdmin',
	},
]

export const settingsOpen = ref(false)
export const settingsTab = ref<SettingsTab>('profile')

// A one-shot read rather than useIsMobile(): openSettings runs from click
// handlers outside any component scope, where a media-query listener would have
// no scope to be torn down with. Same breakpoint, so both agree on what mobile
// means — the dialog only mounts when useIsMobile says desktop, and routing
// here on a different threshold would strand the caller on a page with no
// dialog behind it.
const onMobile = (): boolean =>
	window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`).matches

export const openSettings = (tab: SettingsTab = 'profile'): void => {
	if (onMobile()) {
		router.push(`/settings/${tab}`)
		return
	}
	settingsTab.value = tab
	settingsOpen.value = true
}

// Leave settings, whichever presentation you're in: the dialog closes, and a
// mobile tab page falls back to the list. Callers that navigate somewhere else
// themselves (deleting a team lands on Servers) should set `settingsOpen`
// directly instead, or the two pushes race in the same tick.
export const closeSettings = (): void => {
	settingsOpen.value = false
	if (router.currentRoute.value.path.startsWith('/settings/')) {
		router.replace('/settings')
	}
}
