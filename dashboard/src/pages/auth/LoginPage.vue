<script setup lang="ts">
import { Button, ErrorMessage } from 'frappe-ui'
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import OtpInput from '@/components/common/OtpInput.vue'
import { useAuth } from '@/composables/useAuth'
import { emailError, frappeErrorMessage } from '@/lib/auth'
import { loginDestination } from '@/lib/authRedirect'

const route = useRoute()
const email = ref('')
const otp = ref('')
const codeSent = ref(false)
const submitted = ref(false)
const loading = ref(false)
const error = ref('')
const notice = ref('')

const { requestLoginCode, verifyLoginCode } = useAuth()

async function sendCode() {
	submitted.value = true
	error.value = ''
	notice.value = ''
	if (emailError(email.value)) return

	loading.value = true
	try {
		await requestLoginCode(email.value.trim())
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
	}
}

async function verifyCode() {
	if (loading.value || otp.value.length !== 6) return
	error.value = ''
	loading.value = true
	try {
		const response = await verifyLoginCode(email.value.trim(), otp.value)
		window.location.replace(
			loginDestination(response, route.query['redirect-to']),
		)
	} catch (exception) {
		error.value = frappeErrorMessage(
			exception,
			'That code did not work. Please try again.',
		)
		otp.value = ''
	} finally {
		loading.value = false
	}
}

function changeEmail() {
	codeSent.value = false
	otp.value = ''
	error.value = ''
	notice.value = ''
}
</script>

<template>
	<AuthShell>
		<template v-if="codeSent">
			<h1 class="text-2xl font-semibold text-ink-gray-9">Check your email</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				Enter the 6-digit code we sent to {{ email.trim() }}.
			</p>

			<form class="mt-8 space-y-4" @submit.prevent="verifyCode">
				<OtpInput
					v-model="otp"
					label="Sign-in code"
					:disabled="loading"
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
					:disabled="otp.length !== 6"
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
						class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
						:disabled="loading"
						@click="sendCode"
					>
						Resend code
					</button>
				</div>
			</form>
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
					to="/signup"
					>Create an account
				</RouterLink>
			</p>
		</template>
	</AuthShell>
</template>
