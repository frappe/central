// `navigator.clipboard` exists only in a secure context: HTTPS, or localhost. A bench
// served over plain HTTP on any other host has it undefined, so reading `.writeText`
// off it throws — and an unhandled rejection in a click handler takes the page down.
// It can also reject when the document is not focused or permission is refused, so the
// fallback covers both cases and nothing here is allowed to throw at the caller.

export async function copyToClipboard(value: string): Promise<boolean> {
	if (navigator.clipboard?.writeText) {
		try {
			await navigator.clipboard.writeText(value)
			return true
		} catch {
			// Fall through to the selection-based copy.
		}
	}

	return copyBySelection(value)
}

// Deprecated, and the only thing that works off a secure context. execCommand copies
// the document's selection, so the text has to sit in a selectable node first.
function copyBySelection(value: string): boolean {
	const area = document.createElement('textarea')
	area.value = value
	area.setAttribute('readonly', '')
	area.style.position = 'fixed'
	area.style.top = '-9999px'
	document.body.appendChild(area)

	try {
		area.select()
		// select() alone does not set a range on iOS Safari.
		area.setSelectionRange(0, value.length)
		return document.execCommand('copy')
	} catch {
		return false
	} finally {
		document.body.removeChild(area)
	}
}
