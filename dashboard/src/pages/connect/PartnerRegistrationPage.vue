<script setup lang="ts">
import { Button, ErrorMessage, LoadingText } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import PartnerTeamPicker from '@/components/partner/PartnerTeamPicker.vue'
import { useAuth } from '@/composables/useAuth'
import { usePartnerRegistration } from '@/composables/usePartnerRegistration'
import { requiredError } from '@/lib/auth'
import { formatDate } from '@/lib/format'

const route = useRoute()
const { currentUser } = useAuth()
const {
	registration,
	teams,
	chosen,
	chosenTeam,
	step,
	loadError,
	signInPath,
	signUpPath,
	busy,
	error,
	startNaming,
	createTeam,
	complete,
	switchAccount,
} = usePartnerRegistration(route.params.token as string)

const teamName = ref('')
const submitted = ref(false)
const teamNameError = requiredError('Team name')

const closedMessage = computed(() =>
	registration.value?.status === 'Completed'
		? `${registration.value.partner_name} is already set up on Frappe Cloud.`
		: 'This link has expired. Open Partner Onboarding on Connect to get a new one.',
)

// Connect sent the owner here in the same tab, so the way back stays in it too.
function goBackToConnect() {
	if (registration.value?.connect_url)
		window.location.assign(registration.value.connect_url)
}

function submitTeamName() {
	submitted.value = true
	if (teamNameError(teamName.value)) return
	createTeam(teamName.value)
}
</script>

<template>
	<AuthShell>
		<LoadingText v-if="step === 'loading'" text="Loading" />

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

		<template v-else-if="registration">
			<h1 class="text-2xl font-semibold text-ink-gray-9">
				Set up {{ registration.partner_name }} on Frappe Cloud
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">
				Pick the team that is {{ registration.partner_name }}. Customers who
				hire you on Connect can then add you to their accounts.
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

				<template v-else-if="step === 'sign-in' || step === 'sign-up'">
					<p class="text-p-base text-ink-gray-7">
						This link is for
						<span class="font-medium text-ink-gray-8"
							>{{ registration.email }}</span
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
				</template>

				<template v-else-if="step === 'wrong-account'">
					<p class="text-p-base text-ink-gray-7">
						You are signed in as {{ currentUser }}. Sign in as
						{{ registration.email }}
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

				<template v-else-if="step === 'pick-team'">
					<PartnerTeamPicker
						v-model="chosenTeam"
						:teams="teams"
						:partner-name="registration.partner_name"
						purpose="register"
						@create="startNaming(true)"
					/>
					<ErrorMessage v-if="error" :message="error" />
					<Button
						class="w-full"
						size="md"
						variant="solid"
						:label="
							chosen
								? `Make ${chosen.label} the partner team`
								: 'Pick a team'
						"
						:disabled="!chosen?.available"
						:loading="busy"
						@click="complete"
					/>
					<p
						v-if="registration.expires_on"
						class="text-center text-p-sm text-ink-gray-5"
					>
						Expires {{ formatDate(registration.expires_on) }}
					</p>
				</template>

				<form
					v-else-if="step === 'name-team'"
					class="space-y-4"
					novalidate
					@submit.prevent="submitTeamName"
				>
					<ValidatedFormControl
						v-model="teamName"
						label="Team name"
						:placeholder="`e.g. ${registration.partner_name}`"
						autocomplete="organization"
						v-focus
						:validator="teamNameError"
						:submitted="submitted"
					/>
					<ErrorMessage v-if="error" :message="error" />
					<Button
						class="w-full"
						size="md"
						variant="solid"
						type="submit"
						label="Create team"
						:loading="busy"
					/>
					<Button
						v-if="teams.length"
						class="w-full"
						size="md"
						variant="ghost"
						label="Back"
						:disabled="busy"
						@click="startNaming(false)"
					/>
				</form>

				<template v-else-if="step === 'done'">
					<p class="text-p-base text-ink-gray-7">
						{{ registration.partner_name }}
						is set up. Customers who hire you on Connect get a link to add you
						to their accounts.
					</p>
					<Button
						v-if="registration.connect_url"
						class="w-full"
						size="md"
						variant="solid"
						label="Back to Connect"
						@click="goBackToConnect"
					/>
					<Button
						class="w-full"
						size="md"
						route="/servers"
						label="Open Frappe Cloud"
					/>
				</template>
			</div>
		</template>
	</AuthShell>
</template>
