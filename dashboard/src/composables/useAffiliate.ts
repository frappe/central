import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { submitOrThrow } from '@/lib/frappeCall'
import { __ } from '@/lib/translate'
import type { AffiliateProgram } from '@/types/affiliates'

// One shared read, so the settings tab, its badge and the sidebar item change together.
// immediate:false keeps the request out of module import; the first consumer loads it.
const programCall = useCall<AffiliateProgram>({
	url: method(API.getAffiliate),
	immediate: false,
})

const membershipCall = useCall<AffiliateProgram, { joined: boolean }>({
	url: method(API.setAffiliateProgram),
	method: 'POST',
	immediate: false,
})

async function setJoined(joined: boolean): Promise<void> {
	await submitOrThrow(membershipCall, { joined })
	await programCall.reload()
}

/** The name of a source. No source reads as Direct; one typed by hand reads as typed. */
function sourceLabel(value: string | null): string {
	if (!value) return __('Direct')
	const source = programCall.data?.sources.find((item) => item.name === value)
	return source?.title ?? value
}

export function useAffiliate() {
	// Guarded so consumers that mount together fetch once. A failed read waits for Retry,
	// since the sidebar reads this inside a computed and must not refetch on every change.
	if (!programCall.data && !programCall.loading && !programCall.error)
		programCall.reload()

	const affiliate = computed(() => programCall.data?.affiliate ?? null)

	return {
		affiliate,
		cookieDays: computed(() => programCall.data?.cookie_days ?? null),
		/** Loaded, and the user never joined. Unknown while loading or after a failed read. */
		isNew: computed(() =>
			Boolean(programCall.data && !programCall.data.affiliate),
		),
		products: computed(() => programCall.data?.products ?? []),
		sources: computed(() =>
			(programCall.data?.sources ?? []).filter((source) => source.enabled),
		),
		sourceLabel,
		isJoined: computed(() => affiliate.value?.status === 'Active'),
		isPausedByFrappe: computed(() =>
			Boolean(affiliate.value && !affiliate.value.enabled),
		),
		loading: computed(() => programCall.loading),
		error: computed(() => programCall.error),
		saving: computed(() => membershipCall.loading),
		reload: () => programCall.reload(),
		setJoined,
	}
}
