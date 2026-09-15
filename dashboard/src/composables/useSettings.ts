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
// These double as URL slugs, so they read as addresses rather than internals:
// 'team-settings', not 'team', which would sit confusingly beside 'teams'.
export type SettingsTab =
	| 'profile'
	| 'notifications'
	| 'appearance'
	| 'teams'
	| 'team-settings'

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
		value: 'team-settings',
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

// Each presentation owns its own URL space, so a settings address is never
// ambiguous about which one it means: /settings/:tab is the desktop dialog,
// /mobile-settings/:tab is the page stack. Both name the tab, so a reload or a
// shared link reopens exactly where it left off.
export const SETTINGS_BASE = '/settings'
export const MOBILE_SETTINGS_BASE = '/mobile-settings'

// A one-shot read rather than useIsMobile(): openSettings runs from click
// handlers outside any component scope, where a media-query listener would have
// no scope to be torn down with. Same breakpoint, so both agree on what mobile
// means.
const onMobile = (): boolean =>
	window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`).matches

export const settingsPath = (tab: SettingsTab): string =>
	`${onMobile() ? MOBILE_SETTINGS_BASE : SETTINGS_BASE}/${tab}`

// The dialog covers the page it opened over, and the URL no longer records
// that page — so remember it here and land back on it when settings close.
let returnTo: string | null = null

const inSettings = (path: string): boolean =>
	path.startsWith(SETTINGS_BASE) || path.startsWith(MOBILE_SETTINGS_BASE)

export const openSettings = (tab: SettingsTab = 'profile'): void => {
	const path = router.currentRoute.value.path
	if (!inSettings(path)) returnTo = path
	router.push(settingsPath(tab))
}

/** Leave the desktop dialog for wherever it was opened from. */
export const returnFromSettings = (): void => {
	router.replace(returnTo ?? '/servers')
}

// Leave settings, whichever presentation you're in: a mobile tab page falls
// back to the hub, and the dialog closes — which the route watches, so the
// navigation back out happens there rather than racing with this.
export const closeSettings = (): void => {
	if (router.currentRoute.value.path.startsWith(`${MOBILE_SETTINGS_BASE}/`)) {
		router.replace(MOBILE_SETTINGS_BASE)
		return
	}
	settingsOpen.value = false
}

// Leave settings for somewhere specific instead of back where you came from —
// deleting a team lands on Servers, not on the team page the pencil opened
// settings from. Callers must go through this rather than closing and pushing
// themselves: closing is what triggers the trip back to `returnTo`, and that
// replace supersedes a push issued alongside it, so the caller's destination
// silently loses.
export const closeSettingsTo = (path: string): void => {
	returnTo = path
	closeSettings()
}

// A team switch invalidates wherever settings were opened from: that page
// belongs to the old team and may not even be readable under the new one.
// Home is always safe.
export const forgetSettingsOrigin = (): void => {
	returnTo = null
}
