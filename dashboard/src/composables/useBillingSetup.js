// Billing-profile completeness gate.
//
// A team must complete its billing profile — currency + legal name + address —
// before any money moves (top-up, buy credits, add a payment method). Currency
// is the load-bearing field and is locked once a wallet credit, payment method,
// or invoice exists. The dashboard uses this to block those actions and steer
// the customer to Settings; the backend enforces the same gate as a backstop.

import { computed } from 'vue'
import { useCall } from 'frappe-ui'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'

export function useBillingSetup() {
  const { currentTeam } = useTeam()
  const setup = useCall({
    url: m(API.billingSetup),
    params: () => ({ team: currentTeam.value }),
    refetch: true,
  })

  return {
    setup,
    reload: () => setup.reload(),
    complete: computed(() => !!setup.data?.complete),
    missing: computed(() => setup.data?.missing || []),
    currency: computed(() => setup.data?.currency || null),
    currencyLocked: computed(() => !!setup.data?.currency_locked),
    supportedCurrencies: computed(() => setup.data?.supported_currencies || []),
    loading: computed(() => setup.loading),
  }
}
