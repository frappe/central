import { computed } from 'vue'
import { sidebarSections } from '@/components/navigation/list'

export interface SearchItem {
	name: string
	route: string
	icon: string
}

export const searchIndex = computed(() => {
	const items: SearchItem[] = sidebarSections.value
		.flatMap((section) => section.items)
		.filter((item) => item.condition !== false && item.to)
		.map((item) => ({ name: item.label, route: item.to as string, icon: item.icon }))

	return {
		Pages: { items },
	}
})
