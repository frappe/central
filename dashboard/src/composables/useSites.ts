import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { useFrappeListInvalidation } from '@/composables/common/useFrappeRealtime'
import { getErrorMessage } from '@/lib/toast'

// The team's sites for the unified assets view. Reuses central.api.resources.list_resources
// (server:view gated, team-scoped) filtered to kind=site, so servers aren't refetched here —
// the rich server feed stays in useServerMapData. The Site mirror is kept fresh by Atlas's
// site.* event push; the realtime invalidation below reloads on any Site change.
export interface SiteResource {
	kind: 'site'
	name: string
	label: string
	status: string
	region: string | null
	detail: string | null
}

type ResourcesResponse = { team: string; resources: SiteResource[] }

const feed = useCall<ResourcesResponse, { team: string; kind: string }>({
	url: method(API.listResources),
	params: () => ({ ...teamParams(), kind: 'site' }),
	refetch: true,
	immediate: false,
})

whenTeamReady(() => feed.reload())

let reloadTimer: number | undefined
function reloadOnce(): void {
	window.clearTimeout(reloadTimer)
	reloadTimer = window.setTimeout(() => feed.reload(), 150)
}

export function useSites() {
	useFrappeListInvalidation('Site', reloadOnce, { debounceMs: 0 })

	return {
		sites: computed<SiteResource[]>(() =>
			(feed.data?.resources ?? []).filter((site) => site.status !== 'Terminated'),
		),
		loading: computed(() => feed.loading),
		error: computed(() =>
			feed.error ? getErrorMessage(feed.error, "Couldn't load sites.") : null,
		),
		reload: () => feed.reload(),
	}
}
