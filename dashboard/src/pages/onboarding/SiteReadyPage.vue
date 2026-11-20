<script setup lang="ts">
import { Alert, Button } from 'frappe-ui'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuthErrorMessage from '@/components/auth/AuthErrorMessage.vue'
import AuthShell from '@/components/auth/AuthShell.vue'
import ProductLogo from '@/components/auth/ProductLogo.vue'
import ContactSupportLink from '@/components/common/ContactSupportLink.vue'
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
	isStuck,
	secondsLeft,
	failure,
	error,
	isSigningIn,
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

const supportContext = computed(() => ({
	Topic: 'Site setup',
	Product: title.value,
	Reference: journey.value?.reference,
}))

function tryAgain() {
	router.push({ path: '/onboarding/site', query: carriedQuery(route.query) })
}
</script>

<template>
	<AuthShell show-progress :step="4">
		<template v-if="signInFailed">
			<h1 class="text-2xl-semibold text-ink-gray-9">Your site is ready</h1>
			<p class="mt-2 text-p-base text-ink-gray-5">
				Your site is up, but signing you in is taking longer than usual. Open
				your site to try again.
			</p>
			<Button
				class="mt-8 w-full"
				variant="solid"
				size="md"
				label="Open my site"
				:loading="isSigningIn"
				@click="openSite"
			/>
			<AuthErrorMessage
				v-if="error && !isSigningIn"
				class="mt-4"
				:message="error"
				page="Site setup"
				:context="supportContext"
			/>
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
				:is-delayed="isDelayed || isStuck"
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
				v-if="isStuck"
				class="mt-4"
				theme="red"
				title="Your site is not ready yet"
			>
				<template #description>
					Setup is taking much longer than it should.
					<ContactSupportLink :context="supportContext"
						>Contact support</ContactSupportLink
					>
					and we'll look into it. Keep this page open: it still opens your site
					if setup finishes.
				</template>
			</Alert>
			<Alert
				v-if="stage === 'failed'"
				class="mt-4"
				theme="red"
				title="We couldn't start your server"
				:primary-action="{ label: 'Try again', onClick: tryAgain }"
			>
				<template #description>
					<span v-if="failureDetail" class="block">{{ failureDetail }}</span>
					If this keeps happening,
					<ContactSupportLink :context="supportContext" />.
				</template>
			</Alert>
			<AuthErrorMessage
				v-if="error"
				class="mt-4"
				:message="error"
				page="Site setup"
				:context="supportContext"
			/>
		</template>
	</AuthShell>
</template>
