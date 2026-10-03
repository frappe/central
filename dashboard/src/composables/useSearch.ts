import { useKeyboardShortcut } from 'frappe-ui'
import { ref } from 'vue'

export const searchOpen = ref(false)

export const openSearch = (): void => {
	searchOpen.value = true
}

export const useSearchShortcut = (): void => {
	useKeyboardShortcut({
		combo: 'Mod+K',
		description: 'Search',
		group: 'General',
		allowInInput: true,
		allowInDialog: true,
		handler: openSearch,
	})
}
