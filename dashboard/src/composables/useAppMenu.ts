import { type ColorScheme, useColorScheme } from 'frappe-ui'
import { computed, h } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { openSettings } from '@/composables/useSettings'

const themeOptions: { label: string; icon: string; value: ColorScheme }[] = [
	{ label: 'Light', icon: 'lucide-sun', value: 'light' },
	{ label: 'Dark', icon: 'lucide-moon', value: 'dark' },
	{ label: 'System', icon: 'lucide-monitor', value: 'system' },
]

export const useAppMenu = () => {
	const { currentUser, logout } = useAuth()
	const { colorScheme, setColorScheme } = useColorScheme()

	const logoutAndRedirect = async () => {
		await logout()
		window.location.replace('/dashboard/login')
	}

	const headerMenuItems = computed(() => [
		{
			label: 'Switch team',
			icon: 'lucide-repeat',
			onClick: () => openSettings('teams'),
		},
		{
			label: 'Theme',
			icon: 'lucide-sun-moon',
			submenu: themeOptions.map((theme) => ({
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
		},
	])

	const footerMenuItems = [
		{
			label: 'My profile',
			icon: 'lucide-user',
			onClick: () => openSettings('profile'),
		},
		{ label: 'Sign out', icon: 'lucide-log-out', onClick: logoutAndRedirect },
	]

	return {
		themeOptions,
		headerMenuItems,
		footerMenuItems,
		currentUser,
		logoutAndRedirect,
	}
}
