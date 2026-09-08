import { useKeyboardShortcut } from 'frappe-ui'
import type { Component } from 'vue'
import { defineAsyncComponent, ref } from 'vue'
import { MOBILE_BREAKPOINT } from '@/composables/useIsMobile'
import { router } from '@/router'

const ProfileForm = defineAsyncComponent(
	() => import('@/components/settings/forms/ProfileForm.vue'),
)
const NotificationsForm = defineAsyncComponent(
	() => import('@/components/settings/forms/NotificationsForm.vue'),
)
const PreferencesForm = defineAsyncComponent(
	() => import('@/components/settings/forms/PreferencesForm.vue'),
)
const TeamForm = defineAsyncComponent(
	() => import('@/components/settings/forms/TeamForm.vue'),
)

export type SettingsTab = 'profile' | 'notifications' | 'preferences' | 'team'

export interface SettingsTabDef {
	value: SettingsTab
	/** Which section of the sidebar the entry sits in. */
	group: 'Account' | 'Administration'
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
		label: 'Profile',
		icon: 'lucide-user',
		title: 'My profile',
		description: 'How you appear to your teams.',
		component: ProfileForm,
	},
	{
		value: 'notifications',
		group: 'Account',
		label: 'Notifications',
		icon: 'lucide-bell',
		title: 'Notifications',
		description: "How you're notified on this team.",
		component: NotificationsForm,
		requires: 'member',
	},
	{
		value: 'preferences',
		group: 'Account',
		label: 'Preferences',
		icon: 'lucide-settings-2',
		title: 'Preferences',
		description: 'Manage your personal preferences.',
		component: PreferencesForm,
	},
	{
		value: 'team',
		group: 'Administration',
		label: 'Team',
		icon: 'lucide-users',
		title: 'Team',
		description: 'Your teams, and settings for the active one.',
		component: TeamForm,
	},
]

export const settingsOpen = ref(false)
export const settingsTab = ref<SettingsTab>('profile')

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

export const closeSettings = (): void => {
	settingsOpen.value = false
	if (router.currentRoute.value.path.startsWith('/settings/')) {
		router.replace('/settings')
	}
}

export const useSettingsShortcut = (): void => {
	useKeyboardShortcut({
		combo: 'Mod+Comma',
		description: 'Open settings',
		group: 'General',
		allowInInput: true,
		handler: () => openSettings(),
	})
}
