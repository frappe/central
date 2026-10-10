import type { SearchGroups } from './index'

const HTML_ENTITIES: Record<string, string> = {
	'&': '&amp;',
	'<': '&lt;',
	'>': '&gt;',
	'"': '&quot;',
	"'": '&#39;',
}

const escapeHtml = (text: string): string =>
	text.replace(/[&<>"']/g, (character) => HTML_ENTITIES[character])

/** HTML for a result label with the query in <mark>. Names are user data, so the
 *  text and the query are escaped before the markup is added. */
export const highlightMatch = (text: string, query: string): string => {
	const safeText = escapeHtml(text)
	if (!query) return safeText

	const pattern = escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
	return safeText.replace(new RegExp(`(${pattern})`, 'gi'), '<mark>$1</mark>')
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
