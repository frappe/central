<script setup lang="ts">
import { Avatar, Button, ErrorMessage, LoadingText } from 'frappe-ui'
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import { useAuth } from '@/composables/useAuth'
import { usePartnerRequest } from '@/composables/usePartnerRequest'
import { formatDate } from '@/lib/format'

const route = useRoute()
const { currentUser } = useAuth()
const {
	request,
	step,
	loadError,
	signInPath,
	signUpPath,
	busy,
	error,
	switchAccount,
} = usePartnerRequest(route.params.token as string)

const closedMessage = computed(() => {
	const partner = request.value?.partner_name
	const messages: Record<string, string> = {
		Active: `You already work with ${partner} on Frappe Cloud.`,
		Declined: `You declined ${partner}.`,
		Expired: `This link has expired. Open your project on Connect for a new one.`,
		Ended: `Your work with ${partner} on Frappe Cloud has ended.`,
	}
	return messages[request.value?.status ?? ''] ?? ''
})
</script>

<template>
	<AuthShell>
		<LoadingText
			v-if="step === 'loading' || step === 'opening'"
			text="Loading"
		/>

		<template v-else-if="step === 'invalid'">
			<h1 class="text-2xl font-semibold text-ink-gray-9">
				This link isn’t valid
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">{{ loadError }}</p>
			<Button
				class="mt-8 w-full"
				size="md"
				route="/servers"
				label="Open Frappe Cloud"
			/>
		</template>

		<template v-else-if="request">
			<div class="flex items-center gap-3">
				<Avatar
					:image="request.logo ?? undefined"
					:label="request.partner_name"
					size="2xl"
					shape="square"
				/>
				<span class="text-base font-medium text-ink-gray-7"
					>{{ request.partner_name }}</span
				>
			</div>
			<h1 class="mt-6 text-2xl font-semibold text-ink-gray-9">
				Work with {{ request.partner_name }} on Frappe Cloud
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				You hired {{ request.partner_name }} on Frappe Connect for
				{{ request.project_title }}. Accept them on your Frappe Cloud account.
			</p>

			<div class="mt-8 space-y-4">
				<template v-if="step === 'closed'">
					<p class="text-p-base text-ink-gray-7">{{ closedMessage }}</p>
					<Button
						class="w-full"
						size="md"
						variant="solid"
						:link="request.return_url"
						label="Back to Connect"
					/>
					<Button
						class="w-full"
						size="md"
						route="/servers"
						label="Open Frappe Cloud"
					/>
				</template>

				<template v-else-if="step === 'sign-in' || step === 'sign-up'">
					<p class="text-p-base text-ink-gray-7">
						This link is for
						<span class="font-medium text-ink-gray-8"
							>{{ request.email }}</span
						>.
						{{ step === 'sign-in'
								? 'Sign in with that email to continue.'
								: 'Create your account with that email to continue.' }}
					</p>
					<Button
						class="w-full"
						size="md"
						variant="solid"
						:route="step === 'sign-in' ? signInPath : signUpPath"
						:label="step === 'sign-in' ? 'Sign in' : 'Create an account'"
					/>
					<p
						v-if="request.expires_on"
						class="text-center text-p-sm text-ink-gray-5"
					>
						Expires {{ formatDate(request.expires_on) }}
					</p>
				</template>

				<template v-else-if="step === 'wrong-account'">
					<p class="text-p-base text-ink-gray-7">
						You are signed in as {{ currentUser }}. Sign in as
						{{ request.email }}
						to continue.
					</p>
					<ErrorMessage v-if="error" :message="error" />
					<Button
						class="w-full"
						size="md"
						variant="solid"
						label="Switch account"
						:loading="busy"
						@click="switchAccount"
					/>
				</template>
			</div>
		</template>
	</AuthShell>
</template>
