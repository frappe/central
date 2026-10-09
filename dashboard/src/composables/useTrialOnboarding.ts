import { ref } from 'vue'
import { API } from '@/api/methods'
import { useProduct } from '@/composables/useProduct'
import { sessionReady, useSession } from '@/composables/useSession'
import { forgetFirstTouch, readFirstTouch } from '@/lib/attribution'
import { getFrappe, methodUrl, postFrappe } from '@/lib/auth'
import type { TrialOnboardingStatus } from '@/types/api'

export function useTrialOnboarding() {
	const { productKey } = useProduct()
	const { activeTeam, setActiveTeam, reload } = useSession()
	const requestKey = ref('')

	async function prepareTeam(): Promise<void> {
		await sessionReady
		const result = await postFrappe<{ team: string | null }>(
			methodUrl(API.createTrialTeam),
			readFirstTouch() ?? {},
		)
		forgetFirstTouch()
		if (result.team) {
			setActiveTeam(result.team)
			await reload()
		}
		requestKey.value = savedRequestKey()
	}

	async function readStatus(): Promise<TrialOnboardingStatus> {
		await sessionReady
		return getFrappe<TrialOnboardingStatus>(methodUrl(API.onboardingStatus), {
			team: activeTeam.value || undefined,
			product: productKey.value || undefined,
		})
	}

	function storageKey(): string {
		return `central:onboarding-site-request-key:${window.user}:${activeTeam.value}:${productKey.value}`
	}

	function savedRequestKey(): string {
		const key = storageKey()
		const saved = localStorage.getItem(key)
		if (saved) return saved
		const generated = crypto.randomUUID()
		localStorage.setItem(key, generated)
		return generated
	}

	function resetRequestKey(): void {
		localStorage.removeItem(storageKey())
		requestKey.value = savedRequestKey()
	}

	return {
		team: activeTeam,
		requestKey,
		prepareTeam,
		readStatus,
		resetRequestKey,
	}
}
