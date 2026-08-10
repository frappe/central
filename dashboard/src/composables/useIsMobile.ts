import { onScopeDispose, readonly, ref } from 'vue'

// Reactive viewport check backed by matchMedia. Each caller gets its own listener
// torn down on scope dispose — no module-level global `resize` listener that leaks
// for the life of the tab and reads a stale width captured at import time.
/** Below this width the app is in its mobile presentation (Tailwind's `sm`). */
export const MOBILE_BREAKPOINT = 640

export function useIsMobile(breakpoint = MOBILE_BREAKPOINT) {
	const query = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
	const isMobile = ref(query.matches)
	const onChange = (e: MediaQueryListEvent) => {
		isMobile.value = e.matches
	}
	query.addEventListener('change', onChange)
	onScopeDispose(() => query.removeEventListener('change', onChange))
	return readonly(isMobile)
}
