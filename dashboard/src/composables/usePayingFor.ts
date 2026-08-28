import { useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { errorToast, successToast } from '@/lib/toast'
import type {
	PayingForItem,
	ServiceRow,
	SubscriptionRow,
} from '@/types/billing'

// Servers + team-level metered services as one ranked list, and the two verbs
// that act on them. A module singleton so the Overview card and its tray read the
// same rows and share one in-flight mutation — the card shows the first few, the
// tray shows all of them, and neither should be able to disagree about a total.

const { activeTeam } = useSession()

const servicesCall = useCall<{ services: ServiceRow[] }, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
whenTeamReady(() => servicesCall.reload())

const pause = useCall<unknown, { subscription: string }>({
	url: method(API.pauseSubscription),
	method: 'POST',
	immediate: false,
})
const resume = useCall<unknown, { subscription: string }>({
	url: method(API.resumeSubscription),
	method: 'POST',
	immediate: false,
})

const busy = ref('')
const pendingPause = ref<SubscriptionRow | null>(null)
const pendingAssignProject = ref<SubscriptionRow | null>(null)

export function usePayingFor() {
	const { subscriptions, cycleCosts, reloadSubscriptionGrouping } =
		useBillingOverview()

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

	async function runVerb(
		sub: SubscriptionRow,
		call: typeof pause,
		message: string,
	): Promise<void> {
		busy.value = sub.name
		try {
			await call.submit({ subscription: sub.name })
			successToast(message)
			subscriptions.reload()
			cycleCosts.reload()
		} catch (e) {
			errorToast(e)
		} finally {
			busy.value = ''
		}
	}

	return {
		rows,
		loading,
		currency,
		total,
		busy,
		pendingPause,
		pendingAssignProject,
		openServer,
		askPause: (sub: SubscriptionRow) => {
			pendingPause.value = sub
		},
		confirmPause: (sub: SubscriptionRow) => {
			pendingPause.value = null
			return runVerb(sub, pause, 'Billing paused, server stopping…')
		},
		onResume: (sub: SubscriptionRow) =>
			runVerb(sub, resume, 'Billing resumed, server starting…'),
		askAssignProject: (sub: SubscriptionRow) => {
			pendingAssignProject.value = sub
		},
		onAssignedProject: () => reloadSubscriptionGrouping(),
		reload: () => servicesCall.reload(),
	}
}
