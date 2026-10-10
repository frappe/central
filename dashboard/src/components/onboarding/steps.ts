import type { Component } from 'vue'
import BillingStep from '@/components/onboarding/BillingStep.vue'
import InviteStep from '@/components/onboarding/InviteStep.vue'
import StartStep from '@/components/onboarding/StartStep.vue'
import TeamStep from '@/components/onboarding/TeamStep.vue'
import type { OnboardingStepKey } from '@/types/api'

/** What a step component exposes, so the dialog footer can drive it. A step may
 *  also emit `submit` to run the primary action, for example on Enter. */
export interface OnboardingStepHandle {
	canSubmit: boolean
	submitLabel: string
	saving: boolean
	/** Saves the step's own work. Resolves true when the dialog can move on. */
	submit: () => Promise<boolean>
}

export interface OnboardingStep {
	/** `team` is shown to a user with no team. The others are rows on the team. */
	key: 'team' | OnboardingStepKey
	title: string
	description: string
	component: Component
	isRequired: boolean
}

// The only place that sets the step order. Add a step here and as a component.
export const ONBOARDING_STEPS: OnboardingStep[] = [
	{
		key: 'team',
		title: 'Create your team',
		description:
			'A team holds your servers, sites and billing. You are its owner.',
		component: TeamStep,
		isRequired: true,
	},
	{
		key: 'invite',
		title: 'Invite your team',
		description: `Invitations stay open for ${window.invitation_expiry_days ?? 14} days. Anyone you add can be removed later.`,
		component: InviteStep,
		isRequired: false,
	},
	{
		key: 'billing',
		title: 'Add your billing details',
		description:
			'Invoices use these details, and your country sets the currency.',
		component: BillingStep,
		isRequired: false,
	},
	{
		key: 'start',
		title: 'Get started',
		description: 'Here is how you can get started.',
		component: StartStep,
		isRequired: false,
	},
]
