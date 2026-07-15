<script setup lang="ts">
import { ref, computed } from 'vue'
import { Button, ErrorMessage } from 'frappe-ui'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import SocialLoginButtons from '@/components/auth/SocialLoginButtons.vue'
import OtpInput from '@/components/common/OtpInput.vue'
import { useAuth, type LoginResponse } from '@/composables/useAuth'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import { emailError, frappeErrorMessage, requiredError } from '@/lib/auth'
import { loginDestination } from '@/lib/authRedirect'

const route = useRoute()
const email = ref('')
const password = ref('')
const showPassword = ref(false)
const otp = ref('')
const challenge = ref<LoginResponse | null>(null)
const submitted = ref(false)
const loading = ref(false)
const error = ref('')

const { login, providerLogins } = useAuth()

async function submitPassword() {
	submitted.value = true
	error.value = ''
	if (emailError(email.value) || requiredError('Password')(password.value))
		return

	await runLogin(() =>
		login({
			username: email.value.trim(),
			password: password.value,
		}),
	)
}

async function submitOtp() {
	error.value = ''
	if (otp.value.length !== 6 || !challenge.value?.tmp_id) return

	await runLogin(() =>
		login({
			tmp_id: challenge.value?.tmp_id ?? '',
			otp: otp.value,
		}),
	)
}

async function runLogin(request: () => Promise<LoginResponse>) {
	loading.value = true
	try {
		const response = await request()
		if (response.verification && response.message !== 'Logged In') {
			challenge.value = response
			otp.value = ''
			submitted.value = false
			return
		}
		window.location.replace(
			loginDestination(response, route.query['redirect-to']),
		)
	} catch (exception) {
		error.value = loginError(exception)
	} finally {
		loading.value = false
	}
}

function loginError(exception: unknown): string {
	const message = frappeErrorMessage(
		exception,
		'Unable to sign in. Please try again.',
	)
	return /invalid (login )?credentials/i.test(message)
		? 'The email or password you entered is incorrect.'
		: message
}

function verificationPrompt(): string {
	const verification = challenge.value?.verification
	if (!verification?.setup) {
		return `Verification by ${verification?.method || 'the configured method'} could not be sent. Contact your administrator.`
	}
	if (verification.prompt) return verification.prompt
	return verification.method === 'OTP App'
		? 'Enter the code from your authenticator app.'
		: 'Enter the verification code sent to you.'
}

function cancelChallenge() {
	challenge.value = null
	otp.value = ''
	error.value = ''
}

// Disable the Sign in button while a request is in flight or until both credentials are entered.
const isFormDisabled = computed(
	() => loading.value || !email.value.trim() || !password.value,
)
</script>

<template>
	<AuthShell>
		<template v-if="challenge">
			<h1 class="text-2xl font-semibold text-ink-gray-9">Verify your login</h1>
			<p class="mt-1 text-base text-ink-gray-5">{{ verificationPrompt() }}</p>

			<form class="mt-8 space-y-4" @submit.prevent="submitOtp">
				<OtpInput
					v-model="otp"
					label="Verification code"
					:disabled="loading"
					autofocus
				/>
				<ErrorMessage v-if="error" :message="error" />
				<Button
					type="submit"
					variant="solid"
					size="md"
					class="w-full"
					:loading="loading"
					:disabled="otp.length !== 6"
				>
					Continue
				</Button>
				<Button
					type="button"
					variant="outline"
					size="md"
					class="w-full"
					:disabled="loading"
					@click="cancelChallenge"
				>
					Cancel
				</Button>
			</form>
		</template>

		<template v-else>
			<h1 class="text-2xl font-semibold text-ink-gray-9">Welcome back</h1>
			<p class="mt-1 text-base text-ink-gray-5">
				Sign in to manage your servers.
			</p>

			<form class="mt-8 space-y-4" novalidate @submit.prevent="submitPassword">
				<ValidatedFormControl
					v-model="email"
					label="Work email"
					type="email"
					autocomplete="username"
					placeholder="you@company.com"
					:validator="emailError"
					:submitted="submitted"
				/>
				<div>
					<ValidatedFormControl
						v-model="password"
						label="Password"
						:type="showPassword ? 'text' : 'password'"
						autocomplete="current-password"
						placeholder="Enter your password"
						:validator="requiredError('Password')"
						:submitted="submitted"
					>
						<template #suffix>
							<Button
								type="button"
								variant="ghost"
								size="sm"
								:label="showPassword ? 'Hide password' : 'Show password'"
								:icon="showPassword ? 'lucide-eye-off' : 'lucide-eye'"
								@click="showPassword = !showPassword"
							/>
						</template>
					</ValidatedFormControl>
					<div class="mt-2 text-right">
						<RouterLink
							class="text-p-sm text-ink-gray-5 hover:text-ink-gray-8"
							to="/forgot-password"
						>
							Forgot password?
						</RouterLink>
					</div>
				</div>

				<ErrorMessage v-if="error" :message="error" />
				<Button
					type="submit"
					variant="solid"
					size="md"
					class="w-full"
					:loading="loading"
					:disabled="isFormDisabled"
				>
					Sign in
				</Button>
			</form>

			<SocialLoginButtons :providers="providerLogins" prefix="Continue with" />

			<p class="mt-6 text-center text-p-sm text-ink-gray-5">
				New to Frappe Cloud?
				<RouterLink
					class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
					to="/signup"
				>
					Create an account
				</RouterLink>
			</p>
		</template>
	</AuthShell>
</template>
