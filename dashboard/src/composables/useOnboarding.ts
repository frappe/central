import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import {
	ONBOARDING_STEPS,
	type OnboardingStep,
} from '@/components/onboarding/steps'
import { useAuth } from '@/composables/useAuth'
import { usePartnerRequests } from '@/composables/usePartnerRequests'
import { useSession } from '@/composables/useSession'
import { submitOrThrow } from '@/lib/frappeCall'
import type { OnboardingStepKey } from '@/types/api'

type StepStatus = 'Done' | 'Skipped'

const setStepCall = useCall<
	{ step: OnboardingStepKey; status: StepStatus },
	{ team: string; step: OnboardingStepKey; status: StepStatus }
>({
	url: method(API.setOnboardingStep),
	method: 'POST',
	immediate: false,
})
const skipCall = useCall<{ skipped: boolean }, { team: string }>({
	url: method(API.skipOnboarding),
	method: 'POST',
	immediate: false,
})

// Which onboarding steps the signed-in user still has to answer, and the calls
// that record an answer. A user with no team must create one. A user a partner
// from Connect waits for answers it. An owner answers the steps stored on the
// active team. Anyone else sees no other step.
export function useOnboarding() {
	const session = useSession()
	const { currentUser } = useAuth()

	const partnerRequests = usePartnerRequests()

	const pendingSteps = computed<OnboardingStep[]>(() => {
		if (!session.isLoaded.value || !partnerRequests.isLoaded.value) return []
		// A partner from Connect waits for this user, whichever team they own.
		const hasPartner = partnerRequests.requests.value.length > 0
		const partner: OnboardingStep['key'][] = hasPartner ? ['partner'] : []
		if (!session.teams.value.length) return stepsFor(['team', ...partner])

		const team = session.teams.value.find(
			(row) => row.name === session.activeTeam.value,
		)
		if (!team || team.owner !== currentUser.value) return stepsFor(partner)
		return stepsFor([...partner, ...team.onboarding])
	})

	async function answerStep(
		step: OnboardingStepKey,
		status: StepStatus,
	): Promise<void> {
		await submitOrThrow(setStepCall, {
			team: session.activeTeam.value!,
			step,
			status,
		})
	}

	async function skipAll(): Promise<void> {
		await submitOrThrow(skipCall, { team: session.activeTeam.value! })
		await session.reload()
	}

	return { pendingSteps, answerStep, skipAll, reload: session.reload }
}

function stepsFor(keys: OnboardingStep['key'][]): OnboardingStep[] {
	return ONBOARDING_STEPS.filter((step) => keys.includes(step.key))
}
