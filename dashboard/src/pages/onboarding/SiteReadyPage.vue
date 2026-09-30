<script setup lang="ts">
import { Alert, Button, ErrorMessage, Spinner } from 'frappe-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { API } from '@/api/methods'
import AuthShell from '@/components/auth/AuthShell.vue'
import {
	frappeErrorMessage,
	getFrappe,
	methodUrl,
	postFrappe,
} from '@/lib/auth'

type SiteState = {
	name: string
	status: string
	url: string | null
	ready: boolean
	login_url: string | null
	login_pending: boolean
}

type Creation = {
	action: string
	status: string
	title: string
	error: { message: string } | null
}

type OnboardingStatus = { site: SiteState | null; creation: Creation | null }

const POLL_MS = 1000
// A new Pilot accepts Central seconds after it finishes its bootstrap, so the
// first retries come fast. The schedule still gives up after about 2 minutes.
const LOGIN_RETRY_DELAYS_MS = [
	1000, 1000, 1000, 2000, 2000, 2000, 2000, 5000, 5000, 10000, 10000, 15000,
	15000, 15000, 15000, 20000,
]

const status = ref<OnboardingStatus | null>(null)
const error = ref('')
const router = useRouter()
let timer: ReturnType<typeof setTimeout> | undefined
let loginRetryIndex = 0

const site = computed(() => status.value?.site ?? null)
const creation = computed(() => status.value?.creation ?? null)
const isReady = computed(() => site.value?.ready === true && !error.value)
const isFailed = computed(
	() => site.value?.status === 'Failed' || Boolean(creation.value?.error),
)
// What the customer is waiting on: the machine being built, then the site answering.
const waitingOn = computed(
	() => site.value?.status ?? creation.value?.status ?? 'Pending',
)

async function poll() {
	try {
		status.value = await getFrappe<OnboardingStatus>(
			methodUrl(API.onboardingStatus),
		)
		if (isReady.value) return claim()
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
		const claimed = await postFrappe<SiteState>(methodUrl(API.claimSite), {
			name: site.value!.name,
		})
		if (claimed.login_pending) {
			const retryDelay = LOGIN_RETRY_DELAYS_MS[loginRetryIndex]
			if (retryDelay === undefined) {
				error.value =
					'Your site is up, but we could not sign you in automatically.'
				return
			}
			loginRetryIndex += 1
			timer = setTimeout(claim, retryDelay)
			return
		}
		if (!claimed.login_url) {
			error.value =
				'Your site is up, but we could not sign you in automatically.'
			return
		}
		window.location.assign(claimed.login_url)
	} catch (exception) {
		error.value = frappeErrorMessage(
			exception,
			'Your site is up, but we could not sign you in automatically.',
		)
	}
}

function openSite() {
	if (site.value?.url) window.location.assign(site.value.url)
}

onMounted(poll)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
	<AuthShell show-progress :step="4">
		<template v-if="isReady && site">
			<div
				class="mb-6 grid size-10 place-items-center rounded-5 bg-surface-green-3 text-ink-green-7"
			>
				<span class="lucide-check size-5" aria-hidden="true" />
			</div>
			<h1 class="text-2xl font-semibold text-ink-gray-9">Your site is ready</h1>
			<p class="mt-2 text-p-base text-ink-gray-5">
				Signing you in to
				<span class="font-medium text-ink-gray-8">{{ site.url }}</span>
				as
				<span class="font-medium text-ink-gray-8">Administrator</span>…
			</p>

			<div class="mt-8 flex items-center gap-3 text-ink-gray-5">
				<Spinner size="lg" />
				<span class="text-base">Taking you to your site…</span>
			</div>
		</template>

		<template v-else-if="error && site?.ready">
			<h1 class="text-2xl font-semibold text-ink-gray-9">Your site is ready</h1>
			<p class="mt-2 text-p-base text-ink-gray-5">
				We couldn't sign you in automatically, but your site is up. Open it and
				sign in as Administrator.
			</p>
			<Button
				class="mt-8 w-full"
				variant="solid"
				size="md"
				label="Open my site"
				@click="openSite"
			/>
			<ErrorMessage class="mt-4" :message="error" />
		</template>

		<template v-else-if="isFailed">
			<h1 class="text-2xl font-semibold text-ink-gray-9">
				Setup didn't finish
			</h1>
			<Alert
				class="mt-6"
				theme="red"
				:title="creation?.error?.message || `We couldn't finish setting up your site.`"
				:primary-action="{ label: 'Try again', onClick: () => router.push('/onboarding/site') }"
			/>
		</template>

		<template v-else>
			<h1 class="text-2xl font-semibold text-ink-gray-9">
				Setting up your site…
			</h1>
			<p class="mt-2 text-p-base text-ink-gray-5">
				<template v-if="site?.url">
					We're getting
					<span class="font-medium text-ink-gray-8">{{ site.url }}</span>
					ready. This takes a moment.
				</template>
				<template v-else>
					We're building the server your site runs on. This takes a moment.
				</template>
			</p>
			<div class="mt-8 flex items-center gap-3 text-ink-gray-5">
				<Spinner size="lg" />
				<span class="text-base">{{ waitingOn }}…</span>
			</div>
			<ErrorMessage v-if="error" class="mt-6" :message="error" />
		</template>
	</AuthShell>
</template>
