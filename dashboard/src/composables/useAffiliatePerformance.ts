import { useCall } from 'frappe-ui'
import { computed, type Ref } from 'vue'
import { API, method } from '@/api/methods'
import type { AffiliatePerformance, AffiliatePeriod } from '@/types/affiliates'

/** The signed-in affiliate's counts, read again when the period or product changes. */
export function useAffiliatePerformance(
	period: Ref<AffiliatePeriod>,
	product: Ref<string>,
) {
	const call = useCall<
		AffiliatePerformance,
		{ period: AffiliatePeriod; product?: string }
	>({
		url: method(API.getAffiliatePerformance),
		params: () => ({
			period: period.value,
			product: product.value || undefined,
		}),
		immediate: true,
		refetch: true,
	})

	return {
		performance: computed(() => call.data ?? null),
		loading: computed(() => call.loading),
		error: computed(() => call.error),
		reload: () => call.reload(),
	}
}
