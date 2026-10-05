<script setup lang="ts">
import { Button, ErrorMessage, LoadingText } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import { useAuth } from '@/composables/useAuth'
import { useJoinTeam } from '@/composables/useJoinTeam'
import { requiredError } from '@/lib/auth'
import { formatDate } from '@/lib/format'

const route = useRoute()
const { currentUser } = useAuth()
const {
	invitation,
	step,
	loadError,
	signInPath,
	busy,
	error,
	accept,
	decline,
	signUp,
	switchAccount,
} = useJoinTeam(route.params.token as string)

const fullName = ref('')
const submitted = ref(false)

const closedMessage = computed(() => {
	const messages: Record<string, string> = {
		Accepted: 'This invitation was already accepted.',
		Expired: 'This invitation has expired. Ask the team for a new one.',
		Revoked: 'This invitation was withdrawn by the team.',
		Declined: 'You declined this invitation.',
	}
	return messages[invitation.value?.status ?? ''] ?? ''
})

function submitSignUp() {
	submitted.value = true
	if (requiredError('Full name')(fullName.value)) return
	signUp(fullName.value)
}
</script>

<template>
	<AuthShell>
		<LoadingText v-if="step === 'loading'" text="Loading invitation" />

		<template v-else-if="step === 'invalid'">
			<h1 class="text-2xl font-semibold text-ink-gray-9">
				Invitation not found
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">{{ loadError }}</p>
			<Button
				class="mt-8 w-full"
				size="md"
				route="/login"
				label="Go to sign in"
			/>
		</template>

		<template v-else-if="invitation">
			<h1 class="text-2xl font-semibold text-ink-gray-9">
				Join {{ invitation.team_name }}
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				{{ invitation.invited_by }}
				invited
				<span class="font-medium text-ink-gray-8">{{ invitation.email }}</span>
				to join as {{ invitation.role }}.
			</p>

			<div class="mt-8 space-y-4">
				<template v-if="step === 'closed'">
					<p class="text-p-base text-ink-gray-7">{{ closedMessage }}</p>
					<Button
						class="w-full"
						size="md"
						route="/servers"
						label="Open Frappe Cloud"
					/>
				</template>

				<template v-else-if="step === 'accept'">
					<ErrorMessage v-if="error" :message="error" />
					<Button
						class="w-full"
						size="md"
						variant="solid"
						label="Accept and join"
						:loading="busy"
						@click="accept"
					/>
					<Button
						class="w-full"
						size="md"
						label="Decline"
						:disabled="busy"
						@click="decline"
					/>
					<p class="text-center text-p-sm text-ink-gray-5">
						Expires {{ formatDate(invitation.expires_on) }}
					</p>
				</template>

				<template v-else-if="step === 'wrong-account'">
					<p class="text-p-base text-ink-gray-7">
						You are signed in as {{ currentUser }}. Sign in as
						{{ invitation.email }}
						to accept this invitation.
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

				<template v-else-if="step === 'sign-in'">
					<p class="text-p-base text-ink-gray-7">
						You already have an account. Sign in to accept.
					</p>
					<Button
						class="w-full"
						size="md"
						variant="solid"
						:route="signInPath"
						label="Sign in to accept"
					/>
				</template>

				<form
					v-else-if="step === 'sign-up'"
					class="space-y-4"
					novalidate
					@submit.prevent="submitSignUp"
				>
					<ValidatedFormControl
						v-model="fullName"
						label="Full name"
						autocomplete="name"
						placeholder="Jane Doe"
						v-focus
						:validator="requiredError('Full name')"
						:submitted="submitted"
					/>
					<ErrorMessage v-if="error" :message="error" />
					<Button
						type="submit"
						class="w-full"
						size="md"
						variant="solid"
						:label="`Join ${invitation.team_name}`"
						:loading="busy"
					/>
				</form>
			</div>
		</template>
	</AuthShell>
</template>
