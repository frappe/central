import { dayjs, frappeRequest } from 'frappe-ui'
import { computed, onScopeDispose, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useFrappeDocEventListener } from '@/composables/useFrappeRealtime'
import { useSession } from '@/composables/useSession'
import { backgroundErrorToast, getErrorMessage } from '@/lib/feedback'
import type { ActivityEvent, ActivityPage } from '@/types/activity'

export type ActivityScope = 'server' | 'team'

export function useActivityFeed(
	scope: Ref<ActivityScope>,
	resourceId: Ref<string | null>,
) {
	const { activeTeam } = useSession()
	const category = ref('')
	// [fromISO, toISO]; empty means the whole retention window
	const period = ref<string[]>([])
	const events = ref<ActivityEvent[]>([])
	const nextCursor = ref<string | null>(null)
	const loading = ref(false)
	const loadingMore = ref(false)
	const error = ref('')
	let generation = 0

	const endpoint = computed(() =>
		scope.value === 'server' ? API.serverActivity : API.teamActivity,
	)
	const hasTarget = computed(
		() =>
			Boolean(activeTeam.value) &&
			(scope.value === 'team' || Boolean(resourceId.value)),
	)

	function requestPage(cursor: string | null) {
		return frappeRequest<ActivityPage>({
			url: methodV1(endpoint.value),
			method: 'GET',
			params: {
				team: activeTeam.value,
				...(scope.value === 'server' && resourceId.value
					? { resource_id: resourceId.value }
					: {}),
				...(category.value ? { category: category.value } : {}),
				...periodParams(period.value),
				...(cursor ? { cursor } : {}),
			},
		})
	}

	async function fetchPage(cursor: string | null, replace: boolean) {
		const current = generation
		error.value = ''
		if (replace) loading.value = true
		else loadingMore.value = true

		try {
			const result = await requestPage(cursor)
			if (current !== generation) return

			events.value = replace
				? result.events
				: [...events.value, ...result.events]
			nextCursor.value = result.next_cursor
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(failure, "Activity couldn't be loaded.")
		} finally {
			if (current === generation) {
				loading.value = false
				loadingMore.value = false
			}
		}
	}

	function reset() {
		events.value = []
		nextCursor.value = null
	}

	// The events on screen stay until the new first page replaces them, so a filter change
	// does not blank the list.
	async function reload() {
		generation += 1
		loadingMore.value = false
		if (!hasTarget.value) {
			reset()
			loading.value = false
			return
		}
		await fetchPage(null, true)
	}

	async function loadMore() {
		if (!nextCursor.value || loading.value || loadingMore.value) return
		await fetchPage(nextCursor.value, false)
	}

	// New events land on top; keep the pages and open rows already on screen.
	async function prependNewEvents() {
		if (!events.value.length) return reload()

		const current = generation
		try {
			const result = await requestPage(null)
			if (current !== generation) return
			const seen = new Set(events.value.map((event) => event.id))
			const fresh = result.events.filter((event) => !seen.has(event.id))
			events.value = [...fresh, ...events.value]
		} catch (failure) {
			backgroundErrorToast(failure, "New activity couldn't be loaded.")
		}
	}

	let reloadTimer: number | undefined
	useFrappeDocEventListener('Team', activeTeam, 'activity_changed', () => {
		// The team room has no resource detail, so any append may belong to this page.
		window.clearTimeout(reloadTimer)
		reloadTimer = window.setTimeout(prependNewEvents, 300)
	})
	onScopeDispose(() => window.clearTimeout(reloadTimer))

	// Another team or server must not show the previous one's events while its page loads.
	watch(
		[activeTeam, resourceId, scope],
		() => {
			reset()
			reload()
		},
		{ immediate: true },
	)
	watch([category, period], reload)

	return {
		category,
		period,
		events,
		nextCursor,
		loading,
		loadingMore,
		error,
		reload,
		loadMore,
	}
}

// Whole local days as UTC instants; `until` is the next midnight and is exclusive.
function periodParams([from, to]: string[]): {
	since?: string
	until?: string
} {
	if (!from || !to) return {}
	return {
		since: dayjs(from).startOf('day').toISOString(),
		until: dayjs(to).add(1, 'day').startOf('day').toISOString(),
	}
}
