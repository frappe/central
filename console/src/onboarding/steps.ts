import { defineAsyncComponent, type Component } from 'vue'

// The billing onboarding wizard is a declarative list of steps, rendered as an
// accordion. Each entry is a self-contained section whose `component` renders the
// step body and follows this contract:
//   • props:  `active`   — whether the section is currently expanded
//             `complete` — the wizard's current view of its completion
//   • emits:  `update:complete` (boolean) — report your completion, reactively
//             `advance`           — fired when your primary action finishes, so the
//                                   wizard can open the next step
// A step is LOCKED (collapsed, non-interactive) until every preceding non-optional
// step is complete. Mark a step `optional: true` to let the team finish without it.
//
// To add a step, drop a component under components/onboarding/ that honours the
// contract above and add one entry here. No other file needs to change.

export interface OnboardingStep {
  key: string
  title: string
  description: string
  optional: boolean
  component: Component
}

export const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    key: 'profile',
    title: 'Billing profile',
    description: 'Your billing currency, company details and tax info.',
    optional: false,
    component: defineAsyncComponent(
      () => import('@/components/onboarding/BillingProfileStep.vue'),
    ),
  },
  {
    key: 'payment',
    title: 'Payment method',
    description: 'Add a card or UPI Autopay so invoices are charged automatically.',
    optional: true,
    component: defineAsyncComponent(
      () => import('@/components/onboarding/PaymentMethodStep.vue'),
    ),
  },
]
