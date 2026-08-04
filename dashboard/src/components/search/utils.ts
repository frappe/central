import type { SearchItem } from './index'

type SearchGroup = { items: SearchItem[] }
type SearchGroups = Record<string, SearchGroup>

export const highlightMatch = (text: string, query: string): string => {
	if (!query) return text
	const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
	return text.replace(new RegExp(`(${escaped})`, 'gi'), '<mark>$1</mark>')
}

export const filterIndex = (index: SearchGroups, query: string): SearchGroups => {
	const q = query.trim().toLowerCase()
	if (!q) return index

	const result: SearchGroups = {}
	for (const [group, value] of Object.entries(index)) {
		const items = value.items.filter((item) => item.name.toLowerCase().includes(q))
		if (items.length) result[group] = { items }
	}
	return result
}
