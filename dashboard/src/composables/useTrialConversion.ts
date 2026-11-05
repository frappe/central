import { onScopeDispose, type Ref, ref, watch } from 'vue'
import type { ServerTrial, TrialPlan } from '@/types/billing'

const POLL_MS = 5000
// The gateway confirms a new card within a minute or two. After that, the customer checks again.
const POLL_ATTEMPTS = 24

/** Waits for a new payment method to convert or unlock a trial, and keeps the plan the
 *  site converted to after the trial is gone from the server's config. */
export function useTrialConversion(
	trial: Readonly<Ref<ServerTrial | null>>,
	reload: () => void,
	isOpen: Readonly<Ref<boolean>>,
) {
	const convertedPlan = ref<TrialPlan | null>(null)
	let isAwaiting = false
	let lastPlan: TrialPlan | null = null
	let timer: number | undefined
	let attempts = 0

	function stop(): void {
		window.clearInterval(timer)
		timer = undefined
	}

	function awaitConversion(): void {
		stop()
		isAwaiting = true
		attempts = 0
		reload()
		timer = window.setInterval(() => {
			if (++attempts > POLL_ATTEMPTS) return stop()
			reload()
		}, POLL_MS)
	}

	watch(trial, (current, previous) => {
		if (current) lastPlan = current.plan
		// Converted, held by the spending limit, or an ended trial that can now be kept.
		if (!current || current.held || current.can_keep) stop()
		if (isAwaiting && previous && !current) convertedPlan.value = lastPlan
	})

	watch(isOpen, (open) => {
		if (open) return
		stop()
		isAwaiting = false
		convertedPlan.value = null
	})

	onScopeDispose(stop)

	return { convertedPlan, awaitConversion }
}
