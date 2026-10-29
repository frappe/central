<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthErrorMessage from '@/components/auth/AuthErrorMessage.vue'
import AuthShell from '@/components/auth/AuthShell.vue'
import ProductLogo from '@/components/auth/ProductLogo.vue'
import TermsNotice from '@/components/auth/TermsNotice.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import OtpInput from '@/components/common/OtpInput.vue'
import { useEmailSignIn } from '@/composables/useEmailSignIn'
import { useProduct } from '@/composables/useProduct'
import {
	frappeErrorMessage,
	nameFromEmail,
	queryString,
	requiredError,
} from '@/lib/auth'
import { carriedQuery } from '@/lib/authRedirect'

const RESEND_WAIT_SECONDS = 30

const route = useRoute()
const router = useRouter()
const { sendCode, verifyCode, enterConsole } = useEmailSignIn()
const { productKey } = useProduct()

const email = queryString(route.query.email)
const code = ref('')
const otpInput = ref<InstanceType<typeof OtpInput> | null>(null)
const needsName = ref(false)
const fullName = ref('')
const nameSubmitted = ref(false)
const loading = ref(false)
const redirecting = ref(false)
const error = ref('')
const notice = ref('')
const resendWait = ref(RESEND_WAIT_SECONDS)
const resendTimer = setInterval(() => {
	if (resendWait.value > 0) resendWait.value -= 1
}, 1000)

const backTo = computed(() => ({
	path: '/login',
	query: { ...carriedQuery(route.query), email },
}))

// A code belongs to one email; without it there is nothing to verify.
if (!email) router.replace({ path: '/login', query: carriedQuery(route.query) })

async function verify() {
	if (loading.value || code.value.length !== 6) return
	if (needsName.value) {
		nameSubmitted.value = true
		if (requiredError('Full name')(fullName.value)) return
	}

	loading.value = true
	error.value = ''
	notice.value = ''
	try {
		const name = needsName.value ? fullName.value.trim() : undefined
		const response = await verifyCode(email, code.value, name)
		if ('needs_name' in response) {
			fullName.value = nameFromEmail(email)
			needsName.value = true
			return
		}
		redirecting.value = true
		await enterConsole(response, route.query)
	} catch (exception) {
		redirecting.value = false
		error.value = frappeErrorMessage(exception, 'That code did not work.')
		if (!needsName.value) code.value = ''
	} finally {
		if (!redirecting.value) loading.value = false
		if (!needsName.value) nextTick(() => otpInput.value?.focus())
	}
}

async function resend() {
	loading.value = true
	error.value = ''
	notice.value = ''
	try {
		await sendCode(email)
		notice.value = 'We sent a new code.'
		resendWait.value = RESEND_WAIT_SECONDS
	} catch (exception) {
		error.value = frappeErrorMessage(exception, 'Could not send a new code.')
	} finally {
		loading.value = false
	}
}

onBeforeUnmount(() => clearInterval(resendTimer))
</script>

<template>
	<AuthShell :show-progress="Boolean(productKey)" :step="2">
		<template v-if="needsName">
			<h1 class="flex items-center gap-2 text-xl-semibold text-ink-gray-9">
				<ProductLogo />
				Set up your profile
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				This is how you appear in Frappe Cloud.
			</p>

			<form class="mt-6 space-y-4" novalidate @submit.prevent="verify">
				<ValidatedFormControl
					v-model="fullName"
					label="Full name"
					autocomplete="name"
					placeholder="Your full name"
					v-focus
					:validator="requiredError('Full name')"
					:submitted="nameSubmitted"
				/>
				<AuthErrorMessage
					v-if="error"
					:message="error"
					page="Set up your profile"
				/>
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
			<TermsNotice class="mt-6" />
		</template>

		<template v-else>
			<h1 class="flex items-center gap-2 text-xl-semibold text-ink-gray-9">
				<ProductLogo />
				Check your email
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				We sent a 6-digit code to
				<span class="text-p-base-medium text-ink-gray-8">{{ email }}</span>. If
				it is not in your inbox, check your spam folder.
			</p>

			<form class="mt-6 space-y-4" @submit.prevent="verify">
				<OtpInput
					ref="otpInput"
					v-model="code"
					label="Code"
					:disabled="loading"
					autofocus
					@complete="verify"
				/>
				<p v-if="notice" class="text-p-sm text-ink-gray-6">{{ notice }}</p>
				<AuthErrorMessage v-if="error" :message="error" page="Verify email" />
				<Button
					type="submit"
					variant="solid"
					size="md"
					class="w-full"
					:loading="loading"
					:disabled="code.length !== 6"
				>
					Continue
				</Button>
			</form>

			<div class="mt-6 flex items-center justify-between text-p-sm">
				<RouterLink
					class="text-p-sm-medium text-ink-gray-8 hover:text-ink-gray-9"
					:to="backTo"
				>
					Use a different email
				</RouterLink>
				<button
					type="button"
					class="text-p-sm-medium text-ink-gray-8 hover:text-ink-gray-9 disabled:text-ink-gray-4"
					:disabled="loading || resendWait > 0"
					@click="resend"
				>
					{{ resendWait > 0 ? `Resend code in ${resendWait}s` : 'Resend code' }}
				</button>
			</div>
		</template>
	</AuthShell>
</template>
