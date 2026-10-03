<script setup lang="ts">
import { Button, ErrorMessage } from 'frappe-ui'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import { useEmailSignIn } from '@/composables/useEmailSignIn'
import { emailError, frappeErrorMessage, queryString } from '@/lib/auth'
import { carriedQuery } from '@/lib/authRedirect'

const route = useRoute()
const router = useRouter()
const { sendCode } = useEmailSignIn()

const email = ref(queryString(route.query.email))
const submitted = ref(false)
const loading = ref(false)
const error = ref('')

async function submit() {
	submitted.value = true
	error.value = ''
	if (emailError(email.value)) return

	loading.value = true
	try {
		await sendCode(email.value.trim())
		await router.push({
			path: '/verify',
			query: { ...carriedQuery(route.query), email: email.value.trim() },
		})
	} catch (exception) {
		error.value = frappeErrorMessage(exception, 'Could not send a code.')
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<AuthShell>
		<h1 class="text-xl font-semibold text-ink-gray-9">
			Sign in to Frappe Cloud
		</h1>

		<form class="mt-6 space-y-4" novalidate @submit.prevent="submit">
			<ValidatedFormControl
				v-model="email"
				label="Work email"
				type="email"
				autocomplete="email"
				placeholder="name@company.com"
				autofocus
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
			>
				Continue
			</Button>
		</form>

		<p class="mt-6 text-center text-p-sm text-ink-gray-5">
			New to Frappe Cloud?
			<RouterLink
				class="font-medium text-ink-gray-8 hover:underline"
				:to="{ path: '/signup', query: carriedQuery(route.query) }"
			>
				Create an account
			</RouterLink>
		</p>
	</AuthShell>
</template>
