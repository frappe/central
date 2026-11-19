import { onBeforeUnmount, ref } from 'vue'

const SHOW_DELAY_MS = 40
const HIDE_DELAY_MS = 280

/**
 * Hover intent for the map's card: a short delay in, and a grace period out so the
 * pointer can travel from a node to its card. A locked card ignores hover until hidden,
 * because a menu opened inside it portals to <body> and fires a false mouseleave.
 */
export function useMapHoverCard() {
	const activeKey = ref<string | null>(null)
	const isLocked = ref(false)
	let showTimer: number | undefined
	let hideTimer: number | undefined

	function clearTimers(): void {
		window.clearTimeout(showTimer)
		window.clearTimeout(hideTimer)
	}

	function enter(key: string): void {
		if (isLocked.value) return
		clearTimers()
		showTimer = window.setTimeout(() => (activeKey.value = key), SHOW_DELAY_MS)
	}

	function leave(): void {
		if (isLocked.value) return
		clearTimers()
		hideTimer = window.setTimeout(() => (activeKey.value = null), HIDE_DELAY_MS)
	}

	function keep(): void {
		window.clearTimeout(hideTimer)
	}

	function lock(key: string): void {
		clearTimers()
		activeKey.value = key
		isLocked.value = true
	}

	function hide(): void {
		clearTimers()
		isLocked.value = false
		activeKey.value = null
	}

	onBeforeUnmount(clearTimers)

	return { activeKey, isLocked, enter, leave, keep, lock, hide }
}
