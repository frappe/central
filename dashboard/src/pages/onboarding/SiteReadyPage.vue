<script setup lang="ts">
import { Alert, Button, ErrorMessage } from 'frappe-ui'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import ProductLogo from '@/components/auth/ProductLogo.vue'
import RotatingText from '@/components/common/RotatingText.vue'
import SetupJourney from '@/components/onboarding/SetupJourney.vue'
import { useProduct } from '@/composables/useProduct'
import { useSiteSetup } from '@/composables/useSiteSetup'
import { carriedQuery } from '@/lib/authRedirect'

const route = useRoute()
const router = useRouter()
const { product } = useProduct()
const {
	site,
	journey,
	stage,
	isDelayed,
	secondsLeft,
	failure,
	error,
	openSite,
} = useSiteSetup()

const title = computed(() => product.value?.title)
const signInFailed = computed(() => Boolean(error.value && site.value?.ready))

const heading = computed(() => {
	if (stage.value === 'failed') return `Setup didn't finish`
	if (stage.value === 'arrived')
		return title.value ? `${title.value} is ready` : 'Your site is ready'
	return `Getting ${title.value ?? 'your site'} ready`
})

const lines = computed(() => {
	if (stage.value === 'arrived')
		return [`Opening ${title.value ?? 'your site'}…`]
	if (stage.value === 'failed') return []
	const messages = product.value?.setup_messages
	return messages?.length
		? messages
		: ['Setting things up…', 'Preparing your workspace…', 'Almost there…']
})

const failureDetail = computed(() => {
	const reference = journey.value?.reference
	return [failure.value, reference && `Reference: ${reference}`]
		.filter(Boolean)
		.join(' ')
})

const supportMailto = computed(() => {
	const reference = journey.value?.reference
	const subject = reference
		? `Site setup failed (${reference})`
		: 'Site setup failed'
	return `mailto:cloud@frappe.io?subject=${encodeURIComponent(subject)}`
})

function tryAgain() {
	router.push({ path: '/onboarding/site', query: carriedQuery(route.query) })
}
</script>

<template>
	<AuthShell show-progress :step="4">
		<template v-if="signInFailed">
			<h1 class="text-2xl-semibold text-ink-gray-9">Your site is ready</h1>
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

		<template v-else>
			<h1 class="flex items-center gap-2 text-2xl-semibold text-ink-gray-9">
				<ProductLogo />
				{{ heading }}
			</h1>
			<RotatingText class="mt-2 text-p-base text-ink-gray-5" :lines="lines" />

			<SetupJourney
				class="mt-7"
				:journey="journey"
				:stage="stage"
				:is-delayed="isDelayed"
				:app-title="title"
				:seconds-left="secondsLeft"
			/>

			<Alert
				v-if="isDelayed"
				class="mt-4"
				theme="amber"
				title="This is taking longer than usual"
				description="You can keep this page open. We'll open your site when it's ready."
			/>
			<Alert
				v-if="stage === 'failed'"
				class="mt-4"
				theme="red"
				title="We couldn't start your server"
				:primary-action="{ label: 'Try again', onClick: tryAgain }"
			>
				<template #description>
					<span v-if="failureDetail" class="block">{{ failureDetail }}</span>
					If this keeps happening, email
					<a
						class="text-ink-gray-8 underline underline-offset-2 hover:text-ink-gray-9"
						:href="supportMailto"
						>cloud@frappe.io</a
					>.
				</template>
			</Alert>
			<ErrorMessage v-if="error" class="mt-4" :message="error" />
		</template>
	</AuthShell>
</template>
