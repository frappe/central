import { type ColorScheme, useColorScheme } from 'frappe-ui'
import { computed, h } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useMyInvitations } from '@/composables/useMyInvitations'
import { openSettings } from '@/composables/useSettings'
import { useSupport } from '@/composables/useSupport'

const themeOptions: { label: string; icon: string; value: ColorScheme }[] = [
	{ label: 'System', icon: 'lucide-monitor', value: 'system' },
	{ label: 'Light', icon: 'lucide-sun', value: 'light' },
	{ label: 'Dark', icon: 'lucide-moon', value: 'dark' },
]

export const useAppMenu = () => {
	const { currentUser, logout } = useAuth()
	const { colorScheme, setColorScheme } = useColorScheme()
	const { getContactSupportOption, feedbackOption } = useSupport()
	const { count: invitationCount } = useMyInvitations()
	const helpMenuItems = [getContactSupportOption(), feedbackOption].filter(
		(option) => option !== null,
	)

	const logoutAndRedirect = async () => {
		await logout()
		window.location.replace('/dashboard/login')
	}

	const themeMenuItems = computed(() =>
		themeOptions.map((theme) => ({
			label: theme.label,
			icon: theme.icon,
			selected: colorScheme.value === theme.value,
			onClick: () => setColorScheme(theme.value),
			slots: {
				suffix: ({ selected }: { selected: boolean }) =>
					selected
						? h('span', { class: 'lucide-check size-4 text-ink-gray-6' })
						: null,
			},
		})),
	)

	const footerMenuItems = computed(() => [
		{
			label: 'Settings',
			icon: 'lucide-settings',
			onClick: () => openSettings('profile'),
		},
		// Shown only while an invitation waits, so a signed-in invitee finds it without the email.
		...(invitationCount.value
			? [
					{
						label: `Invitations (${invitationCount.value})`,
						icon: 'lucide-mail',
						onClick: () => openSettings('invitations'),
					},
				]
			: []),
		{
			label: 'Theme',
			icon: 'lucide-sun-moon',
			submenu: themeMenuItems.value,
			slots: { suffix: submenuChevron },
		},
		...(helpMenuItems.length
			? [
					{
						label: 'Help',
						icon: 'lucide-circle-help',
						submenu: helpMenuItems,
						slots: { suffix: submenuChevron },
					},
				]
			: []),
		{ label: 'Sign out', icon: 'lucide-log-out', onClick: logoutAndRedirect },
	])

	return {
		themeOptions,
		footerMenuItems,
		currentUser,
		logoutAndRedirect,
	}
}

function submenuChevron() {
	return h('span', { class: 'flex size-4 items-center justify-center' }, [
		h('span', {
			class: 'lucide-chevron-right size-3.5 text-ink-gray-6',
			'aria-hidden': 'true',
		}),
	])
}
