import type { BreadcrumbsProps } from 'frappe-ui'
import { ref } from 'vue'

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
