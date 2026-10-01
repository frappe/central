<script setup lang="ts">
import { Button, ErrorMessage } from 'frappe-ui'
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import OtpInput from '@/components/common/OtpInput.vue'
import { type LoginCodeResponse, useAuth } from '@/composables/useAuth'
import {
	emailError,
	frappeErrorMessage,
	frappeErrorType,
	queryString,
} from '@/lib/auth'
import { loginDestination } from '@/lib/authRedirect'

const route = useRoute()
const email = ref(queryString(route.query.email))
const otp = ref('')
const otpInput = ref<InstanceType<typeof OtpInput> | null>(null)
const codeSent = ref(false)
const submitted = ref(false)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const policy = ref<LoginCodeResponse | null>(null)
const failedAttempts = ref(0)
// The server never says an account is locked, so the page mirrors the lockout
// its own failed attempts caused instead of offering a resend that cannot work.
const lockout = ref<{ email: string; until: number } | null>(null)
let lockoutTimer: ReturnType<typeof setTimeout> | undefined

const normalizedEmail = computed(() => email.value.trim().toLowerCase())
const isLockedOut = computed(
	() => lockout.value?.email === normalizedEmail.value,
)
const signupLink = computed(() => ({
	path: '/signup',
	query: normalizedEmail.value ? { email: email.value.trim() } : {},
}))

const { requestLoginCode, verifyLoginCode } = useAuth()

async function sendCode() {
	submitted.value = true
	error.value = ''
	notice.value = ''
	if (emailError(email.value)) return
	if (lockout.value && isLockedOut.value) {
		showLockout(lockout.value.until)
		return
	}

	loading.value = true
	try {
		policy.value = await requestLoginCode(email.value.trim())
		notice.value = codeSent.value
			? 'If this email has an active account, we sent a new code.'
			: ''
		codeSent.value = true
		otp.value = ''
	} catch (exception) {
		error.value = frappeErrorMessage(
			exception,
			'Could not send a sign-in code.',
		)
	} finally {
		loading.value = false
		focusCode()
	}
}

async function verifyCode() {
	if (loading.value || isLockedOut.value || otp.value.length !== 6) return
	error.value = ''
	notice.value = ''
	loading.value = true
	try {
		const response = await verifyLoginCode(email.value.trim(), otp.value)
		window.location.replace(
			loginDestination(response, route.query['redirect-to']),
		)
	} catch (exception) {
		otp.value = ''
		if (frappeErrorType(exception) === 'ValidationError')
			failedAttempts.value += 1
		if (policy.value && failedAttempts.value >= policy.value.max_attempts)
			startLockout(policy.value.lockout_minutes)
		else
			error.value = frappeErrorMessage(
				exception,
				'That code did not work. Please try again.',
			)
	} finally {
		loading.value = false
		focusCode()
	}
}

function startLockout(minutes: number) {
	clearTimeout(lockoutTimer)
	const until = Date.now() + minutes * 60_000
	lockout.value = { email: normalizedEmail.value, until }
	lockoutTimer = setTimeout(endLockout, minutes * 60_000)
	showLockout(until)
}

function showLockout(until: number) {
	const minutes = Math.max(1, Math.ceil((until - Date.now()) / 60_000))
	const unit = minutes === 1 ? 'minute' : 'minutes'
	error.value = `Too many incorrect codes. Wait ${minutes} ${unit}, then request a new code.`
}

function endLockout() {
	lockout.value = null
	failedAttempts.value = 0
	error.value = ''
}

function focusCode() {
	if (codeSent.value) nextTick(() => otpInput.value?.focus())
}

function changeEmail() {
	codeSent.value = false
	otp.value = ''
	error.value = ''
	notice.value = ''
	failedAttempts.value = 0
}

onBeforeUnmount(() => clearTimeout(lockoutTimer))
</script>

<template>
	<AuthShell>
		<template v-if="codeSent">
			<h1 class="text-2xl font-semibold text-ink-gray-9">Check your email</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				If an account exists for {{ email.trim() }}, we sent it a 6-digit code.
			</p>

			<form class="mt-8 space-y-4" @submit.prevent="verifyCode">
				<OtpInput
					ref="otpInput"
					v-model="otp"
					label="Sign-in code"
					:disabled="loading || isLockedOut"
					autofocus
				/>
				<p v-if="notice" class="text-p-sm text-ink-gray-6">{{ notice }}</p>
				<ErrorMessage v-if="error" :message="error" />
				<Button
					type="submit"
					variant="solid"
					size="md"
					class="w-full"
					:loading="loading"
					:disabled="otp.length !== 6 || isLockedOut"
				>
					Sign in
				</Button>
				<div class="flex items-center justify-between text-p-sm">
					<button
						type="button"
						class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
						:disabled="loading"
						@click="changeEmail"
					>
						Use a different email
					</button>
					<button
						type="button"
						class="font-medium text-ink-gray-8 hover:text-ink-gray-9 disabled:opacity-50"
						:disabled="loading || isLockedOut"
						@click="sendCode"
					>
						Resend code
					</button>
				</div>
			</form>

			<p class="mt-6 text-center text-p-sm text-ink-gray-5">
				No account yet?
				<RouterLink
					class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
					:to="signupLink"
					>Create an account
				</RouterLink>
			</p>
		</template>

		<template v-else>
			<h1 class="text-2xl font-semibold text-ink-gray-9">Welcome back</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				Sign in to manage your servers.
			</p>

			<form class="mt-8 space-y-4" novalidate @submit.prevent="sendCode">
				<ValidatedFormControl
					v-model="email"
					label="Work email"
					type="email"
					autocomplete="email"
					placeholder="you@company.com"
					:validator="emailError"
					:submitted="submitted"
				/>
				<ErrorMessage v-if="error" :message="error" />
				<Button
					type="submit"
					variant="solid"
					size="md"
					class="w-full"
					:loading="loading"
					:disabled="loading || !email.trim()"
				>
					Send sign-in code
				</Button>
			</form>

			<p class="mt-6 text-center text-p-sm text-ink-gray-5">
				New to Frappe Cloud?
				<RouterLink
					class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
					:to="signupLink"
					>Create an account
				</RouterLink>
			</p>
		</template>
	</AuthShell>
</template>
