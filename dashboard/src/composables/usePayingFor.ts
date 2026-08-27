import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import type {
	PayingForItem,
	ServiceRow,
	SubscriptionRow,
} from '@/types/billing'

const { activeTeam } = useSession()

const servicesCall = useCall<{ services: ServiceRow[] }, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => servicesCall.reload())

export function usePayingFor() {
	const { subscriptions, cycleCosts } = useBillingOverview()

	const loading = computed(
		() =>
			(subscriptions.loading && !subscriptions.data) ||
			(servicesCall.loading && !servicesCall.data),
	)

	const costById = computed(() => {
		const map = new Map<string, number>()
		for (const item of cycleCosts.data?.items ?? [])
			map.set(item.resource_id, item.amount)
		return map
	})

	// Most expensive first — the question behind the card is "where is the money
	// going", and that is the order that answers it.
	const rows = computed<PayingForItem[]>(() => {
		const servers: PayingForItem[] = (subscriptions.data ?? [])
			.filter((sub) => sub.has_server)
			.map((sub) => ({
				kind: 'server' as const,
				id: sub.name,
				cost: sub.resource_id
					? (costById.value.get(sub.resource_id) ?? null)
					: null,
				sub,
			}))
		const metered: PayingForItem[] = (servicesCall.data?.services ?? []).map(
			(service) => ({
				kind: 'service' as const,
				id: service.service_subject,
				cost: costById.value.get(service.service_subject) ?? null,
				service,
			}),
		)
		return [...servers, ...metered].sort(
			(a, b) => (b.cost ?? 0) - (a.cost ?? 0),
		)
	})

	const currency = computed(
		() =>
			cycleCosts.data?.currency ?? subscriptions.data?.[0]?.currency ?? 'INR',
	)
	const total = computed(() => Number(cycleCosts.data?.total ?? 0))

	function openServer(sub: SubscriptionRow): void {
		if (sub.gateway_url) window.open(sub.gateway_url, '_blank', 'noopener')
	}

	return {
		rows,
		loading,
		currency,
		total,
		openServer,
		reload: () => servicesCall.reload(),
	}
}
