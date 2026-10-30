import { frappeRequest } from 'frappe-ui'
import { onScopeDispose, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useFrappeDocEventListener } from '@/composables/useFrappeRealtime'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { ActivityEvent, ServerActivity } from '@/types/activity'

export function useServerActivity(resourceId: Ref<string | null>) {
	const { activeTeam } = useSession()
	const category = ref('')
	const events = ref<ActivityEvent[]>([])
	const nextCursor = ref<string | null>(null)
	const loading = ref(false)
	const loadingMore = ref(false)
	const error = ref('')
	let generation = 0

	async function fetchPage(cursor: string | null, replace: boolean) {
		const current = generation
		error.value = ''
		if (replace) loading.value = true
		else loadingMore.value = true

		try {
			const result = await frappeRequest<ServerActivity>({
				url: methodV1(API.serverActivity),
				method: 'GET',
				params: {
					team: activeTeam.value,
					resource_id: resourceId.value,
					...(category.value ? { category: category.value } : {}),
					...(cursor ? { cursor } : {}),
				},
			})
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

	function clear() {
		generation += 1
		events.value = []
		nextCursor.value = null
		loadingMore.value = false
	}

	async function reload() {
		clear()
		if (!activeTeam.value || !resourceId.value) {
			loading.value = false
			return
		}
		await fetchPage(null, true)
	}

	async function loadMore() {
		if (!nextCursor.value || loading.value || loadingMore.value) return
		await fetchPage(nextCursor.value, false)
	}

	let reloadTimer: number | undefined
	useFrappeDocEventListener('Team', activeTeam, 'activity_changed', () => {
		// The team room has no resource detail, so any append may belong to this page.
		// Coalesce a burst of appends into one reload.
		window.clearTimeout(reloadTimer)
		reloadTimer = window.setTimeout(reload, 300)
	})
	onScopeDispose(() => window.clearTimeout(reloadTimer))

	watch([activeTeam, resourceId, category], reload, { immediate: true })

	return {
		category,
		events,
		nextCursor,
		loading,
		loadingMore,
		error,
		reload,
		loadMore,
	}
}
