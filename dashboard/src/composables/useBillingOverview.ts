import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import type {
	BillingGroup,
	BillingProfile,
	CreditBalance,
	CreditLedgerEntry,
	CycleCosts,
	Forecast,
	NextPayment,
	PaymentMethod,
	SubscriptionRow,
	TeamOverview,
} from '@/types/billing'

// Shared, team-scoped reads behind the consolidated Billing Overview (#69). A
// module singleton — like useCapabilities — so every card on the page reads the
// same data and a single mutation can re-pull the affected slice (e.g. a top-up
// reloads the wallet + the cycle forecast at once). Re-fetches on team switch.

const params = teamParams

const overviewCall = useCall<TeamOverview, { team: string }>({
	url: method(API.teamOverview),
	params,
	immediate: false,
	refetch: true,
})
const forecastCall = useCall<Forecast, { team: string }>({
	url: method(API.forecast),
	params,
	immediate: false,
	refetch: true,
})
const creditCall = useCall<CreditBalance, { team: string }>({
	url: method(API.creditBalance),
	params,
	immediate: false,
	refetch: true,
})
const ledgerCall = useCall<CreditLedgerEntry[], { team: string }>({
	url: method(API.creditLedger),
	params,
	immediate: false,
	refetch: true,
})
const methodsCall = useCall<PaymentMethod[], { team: string }>({
	url: method(API.paymentMethods),
	params,
	immediate: false,
	refetch: true,
})
const profileCall = useCall<BillingProfile, { team: string }>({
	url: method(API.billingProfile),
	params,
	immediate: false,
	refetch: true,
})
const subscriptionsCall = useCall<SubscriptionRow[], { team: string }>({
	url: method(API.subscriptions),
	params,
	immediate: false,
	refetch: true,
})
const groupsCall = useCall<BillingGroup[], { team: string }>({
	url: method(API.billingGroups),
	params,
	immediate: false,
	refetch: true,
})

const nextPaymentCall = useCall<NextPayment, { team: string }>({
	url: method(API.nextPayment),
	params,
	immediate: false,
	refetch: true,
})
const cycleCostsCall = useCall<CycleCosts, { team: string }>({
	url: method(API.cycleCosts),
	params,
	immediate: false,
	refetch: true,
})

whenTeamReady(() => {
	overviewCall.reload()
	forecastCall.reload()
	creditCall.reload()
	ledgerCall.reload()
	methodsCall.reload()
	profileCall.reload()
	subscriptionsCall.reload()
	groupsCall.reload()
	nextPaymentCall.reload()
	cycleCostsCall.reload()
})

export function useBillingOverview() {
	return {
		overview: overviewCall,
		forecast: forecastCall,
		credit: creditCall,
		ledger: ledgerCall,
		methods: methodsCall,
		profile: profileCall,
		subscriptions: subscriptionsCall,
		groups: groupsCall,
		nextPayment: nextPaymentCall,
		cycleCosts: cycleCostsCall,
		// The team's billing currency. The Billing Profile is the source of truth
		// (it's what the setup dialog writes), so read it FIRST: after a profile is
		// saved, reloadProfile() re-pulls it and every consumer (top-up, add-method)
		// reflects the chosen currency immediately — the forecast/credit reads may
		// still be stale INR from before setup and must not win.
		currency: computed(
			() =>
				profileCall.data?.currency ||
				forecastCall.data?.currency ||
				creditCall.data?.currency ||
				overviewCall.data?.currency ||
				'INR',
		),
		// A top-up moves wallet + projection, and can clear a blocker on the next
		// debit (a shortfall covered, a bill brought under the ceiling) — so the
		// outlook is refreshed with them.
		reloadMoney(): void {
			creditCall.reload()
			ledgerCall.reload()
			forecastCall.reload()
			nextPaymentCall.reload()
		},
		// Adding or reordering a method changes who gets charged first, and whether
		// anything can be charged at all.
		reloadMethods(): void {
			methodsCall.reload()
			nextPaymentCall.reload()
		},
		reloadProfile(): void {
			profileCall.reload()
			overviewCall.reload()
		},
		reloadGroups: () => groupsCall.reload(),
		// Tagging a subscription into/out of a group moves it between invoice
		// scopes — both reads carry group state (the subscription's badge, the
		// group's resource_count), so a retag refreshes both at once.
		reloadSubscriptionGrouping(): void {
			subscriptionsCall.reload()
			groupsCall.reload()
		},
	}
}
