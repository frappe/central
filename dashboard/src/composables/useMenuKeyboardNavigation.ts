const navigationKeys = new Set(['ArrowDown', 'ArrowUp', 'Home', 'End'])

/** Navigate menu buttons without taking text-editing keys from the search field. */
export function useMenuKeyboardNavigation(close: () => void) {
	function onKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape') {
			close()
			return
		}
		if (!canNavigate(event)) return

		const container = event.currentTarget as HTMLElement
		const buttons = Array.from(
			container.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'),
		)
		if (!buttons.length) return

		const target = event.target as HTMLElement
		const current = buttons.indexOf(
			target.closest('button') as HTMLButtonElement,
		)
		const next = nextButtonIndex(event.key, current, buttons.length)
		event.preventDefault()
		buttons[next].focus()
	}

	return { onKeydown }
}

function canNavigate(event: KeyboardEvent): boolean {
	const hasModifier = [
		event.altKey,
		event.ctrlKey,
		event.metaKey,
		event.shiftKey,
	].some(Boolean)
	if (hasModifier || !navigationKeys.has(event.key)) return false
	if (!(event.target instanceof HTMLElement)) return false

	const isTextInput = ['INPUT', 'TEXTAREA'].includes(event.target.tagName)
	return !(isTextInput && ['Home', 'End'].includes(event.key))
}

function nextButtonIndex(key: string, current: number, count: number): number {
	if (current < 0) return ['ArrowUp', 'End'].includes(key) ? count - 1 : 0

	switch (key) {
		case 'Home':
			return 0
		case 'End':
			return count - 1
		case 'ArrowUp':
			return (current - 1 + count) % count
		default:
			return (current + 1) % count
	}
}
