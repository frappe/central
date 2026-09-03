import { useShortcut } from 'frappe-ui'
import { ref } from 'vue'

export const searchOpen = ref(false)

export const openSearch = (): void => {
	searchOpen.value = true
}

export const useSearchShortcut = (): void => {
	useShortcut({
		key: 'k',
		ctrl: true,
		description: 'Search',
		group: 'General',
		allowInInput: true,
		allowInDialog: true,
		handler: openSearch,
	})
}
