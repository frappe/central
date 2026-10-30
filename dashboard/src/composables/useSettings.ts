import { useKeyboardShortcut } from 'frappe-ui'
import type { Component } from 'vue'
import { computed, defineAsyncComponent, ref } from 'vue'
import { useCapabilities } from '@/composables/useCapabilities'
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
const InvitationsForm = defineAsyncComponent(
	() => import('@/components/settings/forms/InvitationsForm.vue'),
)
const SSHKeysForm = defineAsyncComponent(
	() => import('@/components/settings/forms/SSHKeysForm.vue'),
)
const WireGuardForm = defineAsyncComponent(
	() => import('@/components/settings/forms/WireGuardForm.vue'),
)

export type SettingsTab =
	| 'profile'
	| 'notifications'
	| 'preferences'
	| 'team'
	| 'invitations'
	| 'ssh-keys'
	| 'wireguard'

/** The sidebar sections, in display order. */
export const SETTINGS_GROUPS = ['Account', 'Administration', 'Access'] as const
export type SettingsGroup = (typeof SETTINGS_GROUPS)[number]

export interface SettingsTabDef {
	value: SettingsTab
	/** Which section of the sidebar the entry sits in. */
	group: SettingsGroup
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
	 * team:delete, 'wireguard' needs server:wireguard. Undefined is always available.
	 */
	requires?: 'member' | 'teamAdmin' | 'wireguard'
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
	{
		value: 'invitations',
		group: 'Administration',
		label: 'Invitations',
		icon: 'lucide-mail',
		title: 'Invitations',
		description: 'Teams that invited you. Accept one to join it.',
		component: InvitationsForm,
	},
	{
		value: 'ssh-keys',
		group: 'Access',
		label: 'SSH keys',
		icon: 'lucide-key-round',
		title: 'SSH keys',
		description: 'Team keys that sign in to your servers.',
		component: SSHKeysForm,
		requires: 'member',
	},
	{
		value: 'wireguard',
		group: 'Access',
		label: 'WireGuard VPN',
		icon: 'lucide-shield',
		title: 'WireGuard VPN',
		description:
			"Connect a laptop or phone to your servers' private addresses through an encrypted tunnel.",
		component: WireGuardForm,
		requires: 'wireguard',
	},
]

/** The settings tabs this member can open on the active team. */
export function useSettingsTabs() {
	const { isMember, canEditTeam, canDeleteTeam, canManageWireGuard } =
		useCapabilities()

	const isAvailable = (tab: SettingsTabDef): boolean => {
		if (tab.requires === 'member') return isMember.value
		if (tab.requires === 'wireguard') return canManageWireGuard.value
		if (tab.requires === 'teamAdmin')
			return canEditTeam.value || canDeleteTeam.value
		return true
	}

	return {
		isAvailable,
		availableTabs: computed(() => SETTINGS_TABS.filter(isAvailable)),
	}
}

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
