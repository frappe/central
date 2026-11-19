<script setup lang="ts">
import { Button } from 'frappe-ui'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthErrorMessage from '@/components/auth/AuthErrorMessage.vue'
import AuthShell from '@/components/auth/AuthShell.vue'
import ProductLogo from '@/components/auth/ProductLogo.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import { useEmailSignIn } from '@/composables/useEmailSignIn'
import { useProduct } from '@/composables/useProduct'
import { emailError, frappeErrorMessage, queryString } from '@/lib/auth'
import { carriedQuery } from '@/lib/authRedirect'

const route = useRoute()
const router = useRouter()
const { sendCode } = useEmailSignIn()
const { product, productKey } = useProduct()

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
	<AuthShell :show-progress="Boolean(productKey)" :step="1">
		<h1 class="flex items-center gap-2 text-xl-semibold text-ink-gray-9">
			<ProductLogo />
			Sign in to Frappe Cloud
		</h1>
		<p v-if="product?.subtitle" class="mt-1 text-p-base text-ink-gray-5">
			{{ product.subtitle }}
		</p>

		<form class="mt-6 space-y-4" novalidate @submit.prevent="submit">
			<ValidatedFormControl
				v-model="email"
				label="Work email"
				type="email"
				autocomplete="email"
				placeholder="name@company.com"
				v-focus
				:validator="emailError"
				:submitted="submitted"
			/>
			<AuthErrorMessage v-if="error" :message="error" page="Sign in" />
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
				class="text-p-sm-medium text-ink-gray-8 hover:underline"
				:to="{ path: '/signup', query: carriedQuery(route.query) }"
			>
				Create an account
			</RouterLink>
		</p>
	</AuthShell>
</template>
