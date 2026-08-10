import { computed, h, ref } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useTheme } from '@/composables/useTheme'

const switchTeamOpen = ref(false)

const themeOptions = [
	{ label: 'Light', icon: 'lucide-sun', value: 'light' },
	{ label: 'Dark', icon: 'lucide-moon', value: 'dark' },
	{ label: 'System', icon: 'lucide-monitor', value: 'system' },
]

export const useAppMenu = () => {
	const { currentUser, logout } = useAuth()
	const { currentTheme, setTheme } = useTheme()

	const logoutAndRedirect = async () => {
		await logout()
		window.location.replace('/dashboard/login')
	}

	const headerMenuItems = computed(() => [
		{
			label: 'Switch team',
			icon: 'lucide-repeat',
			onClick: () => {
				switchTeamOpen.value = true
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

	const footerMenuItems = [
		{ label: 'Profile', icon: 'lucide-user', disabled: true },
		{ label: 'Sign out', icon: 'lucide-log-out', onClick: logoutAndRedirect },
	]

	return {
		switchTeamOpen,
		themeOptions,
		headerMenuItems,
		footerMenuItems,
		currentUser,
		currentTheme,
		setTheme,
		logoutAndRedirect,
	}
}
