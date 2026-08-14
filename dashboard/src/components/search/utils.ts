import type { SearchGroups } from './index'

export const highlightMatch = (text: string, query: string): string => {
	if (!query) return text
	const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
	return text.replace(new RegExp(`(${escaped})`, 'gi'), '<mark>$1</mark>')
}

export const filterIndex = (
	index: SearchGroups,
	query: string,
): SearchGroups => {
	const q = query.trim().toLowerCase()

	// With no query the palette is a menu, not a dump of every record: entity
	// groups stay searchable but only surface once you type.
	if (!q) {
		return Object.fromEntries(
			Object.entries(index).filter(([, value]) => !value.searchOnly),
		)
	}

	const result: SearchGroups = {}

	for (const [group, value] of Object.entries(index)) {
		const items = group.toLowerCase().includes(q)
			? value.items
			: value.items.filter((item) => item.name.toLowerCase().includes(q))
		if (items.length) result[group] = { ...value, items }
	}

	return result
}
