import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { useFrappeListInvalidation } from '@/composables/common/useFrappeRealtime'
import { getErrorMessage } from '@/lib/toast'

// The team's sites for the unified servers view, from central.api.resources.list_site_groups
// (server:view gated, team-scoped). The DB groups by region, counts, and caps each region to
// a preview, so the payload never scales with a team's site count — `count` is the exact total,
// `sites` the (possibly capped) rows to list. The Site mirror is kept fresh by Atlas's site.*
// event push; the realtime invalidation below reloads on any Site change.
export interface SiteResource {
	kind: 'site'
	name: string
	label: string
	status: string
	region: string | null
	detail: string | null
}

interface SiteGroup {
	region: string | null
	count: number
	sites: { name: string; status: string; url: string | null }[]
}

type SiteGroupsResponse = { team: string; groups: SiteGroup[] }

const feed = useCall<SiteGroupsResponse, { team: string }>({
	url: method(API.listSiteGroups),
	params: () => teamParams(),
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

	const groups = computed<SiteGroup[]>(() => feed.data?.groups ?? [])

	return {
		// Flat rows for the searchable panel; each group's preview, region-tagged.
		sites: computed<SiteResource[]>(() =>
			groups.value.flatMap((group) =>
				group.sites.map((site) => ({
					kind: 'site' as const,
					name: site.name,
					label: site.name,
					status: site.status,
					region: group.region,
					detail: site.url,
				})),
			),
		),
		// Exact per-region totals from the DB (may exceed the previewed rows).
		siteCountByRegion: computed<Record<string, number>>(() =>
			Object.fromEntries(groups.value.map((group) => [group.region ?? '', group.count])),
		),
		loading: computed(() => feed.loading),
		error: computed(() =>
			feed.error ? getErrorMessage(feed.error, "Couldn't load sites.") : null,
		),
		reload: () => feed.reload(),
	}
}
