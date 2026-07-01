import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import type {
  TeamOverview,
  Forecast,
  CreditBalance,
  CreditLedgerEntry,
  PaymentMethod,
  BillingProfile,
  SubscriptionRow,
} from '@/types/billing'

// Shared, team-scoped reads behind the consolidated Billing Overview (#69). A
// module singleton — like useCapabilities — so every card on the page reads the
// same data and a single mutation can re-pull the affected slice (e.g. a top-up
// reloads the wallet + the cycle forecast at once). Re-fetches on team switch.

const params = teamParams

const overviewCall = useCall<TeamOverview, { team: string }>({
  url: method(API.teamOverview), params, immediate: false, refetch: true,
})
const forecastCall = useCall<Forecast, { team: string }>({
  url: method(API.forecast), params, immediate: false, refetch: true,
})
const creditCall = useCall<CreditBalance, { team: string }>({
  url: method(API.creditBalance), params, immediate: false, refetch: true,
})
const ledgerCall = useCall<CreditLedgerEntry[], { team: string }>({
  url: method(API.creditLedger), params, immediate: false, refetch: true,
})
const methodsCall = useCall<PaymentMethod[], { team: string }>({
  url: method(API.paymentMethods), params, immediate: false, refetch: true,
})
const profileCall = useCall<BillingProfile, { team: string }>({
  url: method(API.billingProfile), params, immediate: false, refetch: true,
})
const subscriptionsCall = useCall<SubscriptionRow[], { team: string }>({
  url: method(API.subscriptions), params, immediate: false, refetch: true,
})

whenTeamReady(() => {
  overviewCall.reload()
  forecastCall.reload()
  creditCall.reload()
  ledgerCall.reload()
  methodsCall.reload()
  profileCall.reload()
  subscriptionsCall.reload()
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
    // The team's billing currency, resolved from whichever read has it first.
    currency: computed(
      () =>
        forecastCall.data?.currency ||
        creditCall.data?.currency ||
        overviewCall.data?.currency ||
        'INR',
    ),
    // A top-up moves wallet + projection; refresh both.
    reloadMoney(): void {
      creditCall.reload()
      ledgerCall.reload()
      forecastCall.reload()
    },
    reloadMethods: () => methodsCall.reload(),
    reloadProfile(): void {
      profileCall.reload()
      overviewCall.reload()
    },
  }
}
