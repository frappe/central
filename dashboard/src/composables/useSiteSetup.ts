import { dayjsLocal } from 'frappe-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { API } from '@/api/methods'
import { useTrialOnboarding } from '@/composables/useTrialOnboarding'
import { frappeErrorMessage, methodUrl, postFrappe } from '@/lib/auth'
import type {
	SetupPhase,
	TrialOnboardingStatus,
	TrialSiteState,
} from '@/types/api'

/** Central's phase, or arrival, which only the page knows. */
export type SetupStage = SetupPhase | 'arrived'

const POLL_MS = 1000
// Central never times out a site creation. The slowest real setup took about 3.5 minutes,
// so past this the page treats it as stuck and offers support.
const STUCK_AFTER_SECONDS = 10 * 60
// A new Pilot accepts Central seconds after it finishes its bootstrap, so the
// first retries come fast. The schedule still gives up after about 2 minutes.
const LOGIN_RETRY_DELAYS_MS = [
	1000, 1000, 1000, 2000, 2000, 2000, 2000, 5000, 5000, 10000, 10000, 15000,
	15000, 15000, 15000, 20000,
]
const SIGN_IN_FAILED =
	'Your site is up, but we could not sign you in automatically.'

/** Follows a new trial site until it answers, then signs the customer in and leaves. */
export function useSiteSetup() {
	const { readStatus } = useTrialOnboarding()
	const status = ref<TrialOnboardingStatus | null>(null)
	const error = ref('')
	const loginUrl = ref<string | null>(null)
	const isSigningIn = ref(false)
	const now = ref(Date.now())
	let timer: ReturnType<typeof setTimeout> | undefined
	let clock: ReturnType<typeof setInterval> | undefined
	let loginRetryIndex = 0

	const site = computed(() => status.value?.site ?? null)
	const journey = computed(() => status.value?.journey ?? null)
	// A creation error such as REFRESH_FAILED is transient until the request itself fails.
	const isFailed = computed(() => journey.value?.phase === 'failed')
	const failure = computed(() => status.value?.creation?.error?.message ?? '')
	const secondsWaited = computed(() => {
		const started = journey.value?.started_at
		return started ? (now.value - dayjsLocal(started).valueOf()) / 1000 : 0
	})
	const secondsLeft = computed(() => {
		const eta = journey.value?.eta_seconds
		return eta ? Math.round(eta - secondsWaited.value) : null
	})

	const stage = computed<SetupStage>(() => {
		if (loginUrl.value) return 'arrived'
		if (isFailed.value) return 'failed'
		return journey.value?.phase ?? 'booking'
	})
	const isWaiting = computed(() =>
		['booking', 'server', 'app'].includes(stage.value),
	)
	const isStuck = computed(
		() => isWaiting.value && secondsWaited.value > STUCK_AFTER_SECONDS,
	)
	// Past twice the usual wait the page says so. The progress keeps the real phase.
	const isDelayed = computed(() => {
		const eta = journey.value?.eta_seconds
		return Boolean(
			eta && isWaiting.value && !isStuck.value && secondsWaited.value > eta * 2,
		)
	})

	async function poll() {
		try {
			status.value = await readStatus()
			if (site.value?.ready) return claim()
			if (isFailed.value) return
		} catch (exception) {
			error.value = frappeErrorMessage(
				exception,
				'Lost track of your site. Refresh to retry.',
			)
			return
		}
		timer = setTimeout(poll, POLL_MS)
	}

	// Ready means the site answered. Claiming hands back a way in and schedules the
	// customer's name behind the response. A new Pilot can reject Central authentication
	// briefly, so only that state is retried without starting the rename.
	async function claim() {
		try {
			const claimed = await postFrappe<TrialSiteState>(
				methodUrl(API.claimSite),
				{ name: site.value!.name },
			)
			if (claimed.login_pending) return retryClaim()
			if (!claimed.login_url) return failSignIn(SIGN_IN_FAILED)
			arrive(claimed.login_url)
		} catch (exception) {
			failSignIn(frappeErrorMessage(exception, SIGN_IN_FAILED))
		}
	}

	function retryClaim() {
		const retryDelay = LOGIN_RETRY_DELAYS_MS[loginRetryIndex]
		if (retryDelay === undefined) return failSignIn(SIGN_IN_FAILED)
		loginRetryIndex += 1
		timer = setTimeout(claim, retryDelay)
	}

	function failSignIn(message: string) {
		error.value = message
		isSigningIn.value = false
	}

	function arrive(url: string) {
		error.value = ''
		loginUrl.value = url
		// Long enough to read "Arrived", short enough that nobody waits on it.
		timer = setTimeout(() => window.location.assign(url), 1200)
	}

	// The bare address opens on a login page the customer has no password for, so sign in again.
	function openSite() {
		if (isSigningIn.value) return
		isSigningIn.value = true
		loginRetryIndex = 0
		claim()
	}

	onMounted(() => {
		clock = setInterval(() => (now.value = Date.now()), 1000)
		poll()
	})
	onUnmounted(() => {
		clearTimeout(timer)
		clearInterval(clock)
	})

	return {
		site,
		journey,
		stage,
		isDelayed,
		isStuck,
		secondsLeft,
		failure,
		error,
		isSigningIn,
		openSite,
	}
}
