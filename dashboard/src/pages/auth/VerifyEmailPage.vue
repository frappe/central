<script setup lang="ts">
import { Button, ErrorMessage } from 'frappe-ui'
import { computed, nextTick, ref } from 'vue'
import { type LocationQueryRaw, useRoute, useRouter } from 'vue-router'
import { API } from '@/api/methods'
import AuthShell from '@/components/auth/AuthShell.vue'
import OtpInput from '@/components/common/OtpInput.vue'
import {
	frappeErrorMessage,
	frappeErrorType,
	methodUrl,
	postFrappe,
	queryString,
} from '@/lib/auth'

// The pending signup is gone or locked; only a fresh signup can issue a code.
const RESTART_ERRORS = new Set(['SignupCodeExpiredError', 'SignupLockedError'])

const route = useRoute()
const router = useRouter()
const email = queryString(route.query.email)
const product = computed(() => queryString(route.query.product))
const isProductSignup = computed(() => Boolean(product.value))
const signupSteps = computed(() => (isProductSignup.value ? 4 : 2))

const otp = ref('')
const otpInput = ref<InstanceType<typeof OtpInput> | null>(null)
const loading = ref(false)
const redirecting = ref(false)
const resent = ref(false)
const error = ref('')
const needsRestart = ref(false)

// Without an email there is no pending signup to verify.
if (!email) router.replace({ path: '/signup', query: signupQuery() })

async function verify() {
	if (loading.value || needsRestart.value || otp.value.length !== 6) return
	loading.value = true
	resent.value = false
	error.value = ''
	try {
		await postFrappe(methodUrl(API.verifySignup), { email, code: otp.value })
		// Full navigation so the SPA re-boots with the now-authenticated session.
		// `replace` (not `href`) so the verify page leaves the back stack — Back from
		// the next screen can't land on it (the guard also resumes authenticated state).
		redirecting.value = true
		window.location.replace(signupDestination())
	} catch (exception) {
		showError(exception, 'That code did not work. Please try again.')
		otp.value = ''
	} finally {
		if (!redirecting.value) loading.value = false
		focusCode()
	}
}

async function resend() {
	if (loading.value || needsRestart.value) return
	loading.value = true
	resent.value = false
	error.value = ''
	try {
		await postFrappe(methodUrl(API.resendSignupCode), { email })
		resent.value = true
	} catch (exception) {
		showError(exception, 'Could not resend the code.')
	} finally {
		loading.value = false
		focusCode()
	}
}

function showError(exception: unknown, fallback: string) {
	error.value = frappeErrorMessage(exception, fallback)
	needsRestart.value = RESTART_ERRORS.has(frappeErrorType(exception) ?? '')
}

function focusCode() {
	if (!needsRestart.value) nextTick(() => otpInput.value?.focus())
}

function startAgain() {
	router.push({
		path: '/signup',
		query: { ...signupQuery(), ...(email ? { email } : {}) },
	})
}

function signupDestination(): string {
	return isProductSignup.value
		? '/dashboard/onboarding/site'
		: '/dashboard/servers'
}

function signupQuery(): LocationQueryRaw {
	return isProductSignup.value ? { product: product.value } : {}
}
</script>

<template>
	<AuthShell show-progress :step="2" :steps="signupSteps">
		<h1 class="text-2xl font-semibold text-ink-gray-9">Verify your email</h1>
		<p class="mt-2 text-p-base text-ink-gray-5">
			Enter the 6-digit code we sent to
			<span class="font-medium text-ink-gray-8">{{ email }}</span>.
		</p>

		<form class="mt-8 space-y-4" @submit.prevent="verify">
			<OtpInput
				ref="otpInput"
				v-model="otp"
				label="Verification code"
				:disabled="loading || needsRestart"
				autofocus
				@complete="verify"
			/>
			<p
				v-if="resent"
				class="rounded-4 bg-surface-green-2 px-3 py-2 text-p-sm text-ink-green-2"
			>
				A new code has been sent.
			</p>
			<ErrorMessage v-if="error" :message="error" />

			<Button
				v-if="needsRestart"
				variant="solid"
				size="md"
				class="w-full"
				@click="startAgain"
			>
				Start again
			</Button>
			<Button
				v-else
				type="submit"
				variant="solid"
				size="md"
				class="w-full"
				:loading="loading"
				:disabled="otp.length !== 6"
			>
				Verify and continue
			</Button>
		</form>

		<div class="mt-6 flex items-center justify-between text-p-sm">
			<button
				type="button"
				class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
				@click="router.push({ path: '/signup', query: signupQuery() })"
			>
				Use a different email
			</button>
			<button
				v-if="!needsRestart"
				type="button"
				class="font-medium text-ink-gray-8 hover:text-ink-gray-9 disabled:opacity-50"
				:disabled="loading"
				@click="resend"
			>
				Resend code
			</button>
		</div>
	</AuthShell>
</template>
