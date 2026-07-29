import { ref } from 'vue'
import type { BreadcrumbsProps } from 'frappe-ui'

type BreadcrumbItem = BreadcrumbsProps['items'][number]

const items = ref<BreadcrumbItem[] | null>(null)

export function useBreadcrumbs() {
	return {
		items,
		setBreadcrumbs: (value: BreadcrumbItem[]) => {
			items.value = value
		},
		resetBreadcrumbs: () => {
			items.value = null
		},
	}
}
