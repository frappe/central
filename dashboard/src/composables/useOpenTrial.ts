import { onUnmounted, ref } from 'vue'
import { API } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import {
	frappeErrorMessage,
	getFrappe,
	methodUrl,
	postFrappe,
} from '@/lib/auth'
import type {
	OpenTrial,
	TrialAppInstall,
	TrialAppInstallProgress,
	TrialSiteState,
} from '@/types/api'

/** Where the open-trial card is: waiting for the customer, or running one of its actions. */
export type OpenTrialStep =
	| 'idle'
	| 'installing'
	| 'installed'
	| 'opening'
	| 'deleting'

const POLL_MS = 3000
// A sleeping trial server wakes on the first request, so a sign-in waits for it.
const OPEN_ATTEMPTS = 20
// Terminating a server takes about a minute. After this, the customer reloads.
const DELETE_ATTEMPTS = 60
// Two minutes of unanswered polls ends the wait, so the page never spins forever.
const UNREACHABLE_POLLS = 40

/** The owner's open free trial, and the actions a new signup offers on it. */
export function useOpenTrial() {
	const { activeTeam } = useSession()
	const trial = ref<OpenTrial | null>(null)
	const step = ref<OpenTrialStep>('idle')
	const error = ref('')
	/** Tasks ahead of the install while it waits in the server's queue. */
	const queuePosition = ref<number | null>(null)
	const installStartedAt = ref<string | null>(null)
	let timer: ReturnType<typeof setTimeout> | undefined
	let unansweredPolls = 0

	async function load(): Promise<OpenTrial | null> {
		trial.value = await getFrappe<OpenTrial | null>(
			methodUrl(API.getOpenTrial),
			{
				team: activeTeam.value || undefined,
			},
		)
		return trial.value
	}

	function installKey(product: string): string {
		return `central:trial-app-install:${window.user}:${product}`
	}

	async function installApp(product: string): Promise<void> {
		step.value = 'installing'
		error.value = ''
		queuePosition.value = null
		installStartedAt.value = null
		unansweredPolls = 0
		try {
			const install = await postFrappe<TrialAppInstall>(
				methodUrl(API.installTrialApp),
				{ product, team: activeTeam.value || undefined },
			)
			if (install.status === 'success' || !install.task_id) {
				step.value = 'installed'
				return
			}
			sessionStorage.setItem(installKey(product), JSON.stringify(install))
			followInstall(product, install)
		} catch (exception) {
			fail(
				frappeErrorMessage(
					exception,
					'Could not start the install. Try again.',
				),
			)
		}
	}

	/** Pick up an install that this tab started before a reload. */
	function resumeInstall(product: string): void {
		const saved = sessionStorage.getItem(installKey(product))
		if (!saved) return
		step.value = 'installing'
		followInstall(product, JSON.parse(saved) as TrialAppInstall)
	}

	async function followInstall(
		product: string,
		install: TrialAppInstall,
	): Promise<void> {
		try {
			const progress = await postFrappe<TrialAppInstallProgress>(
				methodUrl(API.trialAppInstall),
				{
					site: install.site,
					task_id: install.task_id,
					product,
					team: activeTeam.value || undefined,
				},
			)
			if (isStillRunning(progress)) {
				timer = setTimeout(() => followInstall(product, install), POLL_MS)
				return
			}
			sessionStorage.removeItem(installKey(product))
			if (progress.status === 'success') step.value = 'installed'
			else if (progress.status === 'unreachable')
				fail('Your site stopped answering. Try again in a few minutes.')
			else
				fail(
					progress.error ||
						'The install stopped before it finished. Try again.',
				)
		} catch (exception) {
			sessionStorage.removeItem(installKey(product))
			fail(
				frappeErrorMessage(
					exception,
					'Could not read the install progress. Reload this page to check again.',
				),
			)
		}
	}

	function isStillRunning(progress: TrialAppInstallProgress): boolean {
		if (progress.status === 'unreachable')
			return ++unansweredPolls < UNREACHABLE_POLLS
		unansweredPolls = 0
		queuePosition.value = progress.queue_position
		installStartedAt.value = progress.started_at
		return progress.status === 'queued' || progress.status === 'running'
	}

	/** Sign in to the trial site, on the page of `product` when given. */
	async function openSite(product?: string, attempt = 1): Promise<void> {
		if (!trial.value?.site) return
		step.value = 'opening'
		error.value = ''
		try {
			const state = await postFrappe<TrialSiteState>(methodUrl(API.loginSite), {
				name: trial.value.site,
				product,
			})
			if (state.login_url) return window.location.assign(state.login_url)
			if (attempt < OPEN_ATTEMPTS) {
				timer = setTimeout(() => openSite(product, attempt + 1), POLL_MS)
				return
			}
			fail('Your site did not wake up. Try again in a minute.')
		} catch (exception) {
			fail(
				frappeErrorMessage(
					exception,
					'Could not sign you in to your site. Try again in a minute.',
				),
			)
		}
	}

	/** Terminate the open trial's server, then wait until the trial is closed. */
	async function deleteSite(): Promise<boolean> {
		if (!trial.value?.site) return false
		step.value = 'deleting'
		error.value = ''
		try {
			await postFrappe(methodUrl(API.terminateSite), { name: trial.value.site })
		} catch (exception) {
			fail(
				frappeErrorMessage(exception, 'Could not delete your site. Try again.'),
			)
			return false
		}
		return waitUntilClosed(trial.value.site)
	}

	async function waitUntilClosed(site: string): Promise<boolean> {
		for (let attempt = 0; attempt < DELETE_ATTEMPTS; attempt++) {
			await new Promise((resolve) => (timer = setTimeout(resolve, POLL_MS)))
			const open = await load().catch(() => trial.value)
			if (open?.site !== site) {
				step.value = 'idle'
				return true
			}
		}
		fail('Your site is still being deleted. Reload this page in a minute.')
		return false
	}

	function fail(message: string): void {
		step.value = 'idle'
		error.value = message
	}

	onUnmounted(() => clearTimeout(timer))

	return {
		trial,
		step,
		error,
		queuePosition,
		installStartedAt,
		load,
		installApp,
		resumeInstall,
		openSite,
		deleteSite,
	}
}
