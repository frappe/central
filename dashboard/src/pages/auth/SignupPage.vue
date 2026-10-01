<script setup lang="ts">
import { Button, ErrorMessage } from 'frappe-ui'
import { computed, ref } from 'vue'
import { type LocationQueryRaw, useRoute, useRouter } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import SocialLoginButtons from '@/components/auth/SocialLoginButtons.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import { useAuth } from '@/composables/useAuth'
import {
	emailError,
	frappeErrorMessage,
	postFrappe,
	queryString,
	requiredError,
} from '@/lib/auth'

const route = useRoute()
const router = useRouter()
const fullName = ref('')
const email = ref(queryString(route.query.email))
const submitted = ref(false)
const loading = ref(false)
const error = ref('')
const hasExistingAccount = ref(false)

const { providerLogins } = useAuth()
const product = computed(() => queryString(route.query.product))
const isProductSignup = computed(() => Boolean(product.value))
const signupSteps = computed(() => (isProductSignup.value ? 4 : 2))
const subheading = computed(() =>
	isProductSignup.value
		? 'A couple of minutes from here to naming your first site.'
		: 'Verify your email to start managing your servers.',
)

async function signup() {
	submitted.value = true
	error.value = ''
	hasExistingAccount.value = false
	if (requiredError('Full name')(fullName.value) || emailError(email.value))
		return

	loading.value = true
	try {
		const response = await postFrappe<[number, string]>(
			'/api/method/central.api.auth.sign_up',
			{
				full_name: fullName.value.trim(),
				email: email.value.trim(),
			},
		)
		const [status, message] = response ?? [0, 'Unable to create your account.']
		if (status !== 1) {
			error.value = message
			hasExistingAccount.value = Boolean(response)
			return
		}
		await router.push({
			path: '/signup/verify',
			query: verificationQuery(),
		})
	} catch (exception) {
		error.value = frappeErrorMessage(
			exception,
			'Unable to create your account.',
		)
	} finally {
		loading.value = false
	}
}

function verificationQuery(): LocationQueryRaw {
	return {
		email: email.value.trim(),
		...(product.value ? { product: product.value } : {}),
	}
}

function loginQuery(): LocationQueryRaw {
	return {
		...(email.value.trim() ? { email: email.value.trim() } : {}),
		...(isProductSignup.value
			? { 'redirect-to': '/dashboard/onboarding/site' }
			: {}),
	}
}
</script>

<template>
	<AuthShell show-progress :steps="signupSteps">
		<h1 class="text-2xl font-semibold text-ink-gray-9">Create your account</h1>
		<p class="mt-1 text-p-base text-ink-gray-5">
			{{ subheading }}
		</p>

		<form class="mt-8 space-y-4" novalidate @submit.prevent="signup">
			<ValidatedFormControl
				v-model="fullName"
				label="Full name"
				autocomplete="name"
				placeholder="Jane Doe"
				autofocus
				:validator="requiredError('Full name')"
				:submitted="submitted"
			/>
			<ValidatedFormControl
				v-model="email"
				label="Work email"
				type="email"
				autocomplete="email"
				placeholder="jane@company.com"
				:validator="emailError"
				:submitted="submitted"
			/>

			<div v-if="error" class="space-y-1">
				<ErrorMessage :message="error" />
				<RouterLink
					v-if="hasExistingAccount"
					class="text-p-sm font-medium text-ink-gray-8 hover:text-ink-gray-9"
					:to="{ path: '/login', query: loginQuery() }"
				>
					Sign in with this email
				</RouterLink>
			</div>
			<Button
				type="submit"
				variant="solid"
				size="md"
				class="w-full"
				:loading="loading"
			>
				Continue
			</Button>
		</form>

		<SocialLoginButtons :providers="providerLogins" prefix="Continue with" />

		<p class="mt-6 text-center text-p-sm text-ink-gray-5">
			Already have an account?
			<RouterLink
				class="font-medium text-ink-gray-8 hover:text-ink-gray-9"
				:to="{ path: '/login', query: loginQuery() }"
			>
				Sign in
			</RouterLink>
		</p>
	</AuthShell>
</template>
