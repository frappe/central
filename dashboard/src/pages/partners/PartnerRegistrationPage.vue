<script setup lang="ts">
import { Button, ErrorMessage, FormControl, LoadingText } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import CreateTeamDialog from '@/components/team/CreateTeamDialog.vue'
import { useAuth } from '@/composables/useAuth'
import { usePartnerRegistration } from '@/composables/usePartnerRegistration'
import { __ } from '@/lib/translate'

const route = useRoute()
const { currentUser } = useAuth()
const {
	registration,
	step,
	loadError,
	signInPath,
	busy,
	error,
	complete,
	switchAccount,
	reload,
} = usePartnerRegistration(route.params.token as string)

const selectedTeam = ref('')
const creatingTeam = ref(false)
const teams = computed(() => registration.value?.teams ?? [])
const teamOptions = computed(() =>
	teams.value.map((team) => ({ label: team.team_name, value: team.name })),
)

// One team needs no choice, and a team created here is the one the owner meant.
watch(teams, (options, previous) => {
	const added = options.find(
		(team) => !previous?.some((old) => old.name === team.name),
	)
	if (options.length === 1) selectedTeam.value = options[0].name
	else if (previous?.length && added) selectedTeam.value = added.name
})

watch(creatingTeam, (isOpen) => {
	if (!isOpen) reload()
})

// With no team to choose, creating one is the only next step.
const description = computed(() => {
	const partner = registration.value?.partner_name ?? ''
	return step.value === 'choose-team' && !teams.value.length
		? __('Create a team for {0}. Customers add this team as their partner.', [
				partner,
			])
		: __('Choose the team for {0}. Customers add this team as their partner.', [
				partner,
			])
})

const signInMessage = computed(() => {
	const email = registration.value?.owner_email ?? ''
	return registration.value?.has_account
		? __('Sign in as {0} to continue.', [email])
		: __('Create an account for {0} to continue.', [email])
})
</script>

<template>
	<AuthShell>
		<LoadingText v-if="step === 'loading'" :text="__('Loading registration')" />

		<template v-else-if="step === 'invalid'">
			<h1 class="text-xl-semibold text-ink-gray-9">
				{{ __('Registration not found') }}
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">{{ loadError }}</p>
			<Button
				class="mt-6 w-full"
				size="md"
				route="/login"
				:label="__('Go to sign in')"
			/>
		</template>

		<template v-else-if="registration">
			<h1 class="text-xl-semibold text-ink-gray-9">
				{{ __('Set up {0} on Frappe Cloud', [registration.partner_name]) }}
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">{{ description }}</p>

			<div v-if="step === 'closed'" class="mt-6 space-y-4">
				<p class="text-p-base text-ink-gray-7">
					{{ __('This partner already has a Frappe Cloud team.') }}
				</p>
				<Button
					class="w-full"
					size="md"
					route="/servers"
					:label="__('Open Frappe Cloud')"
				/>
			</div>

			<div v-else-if="step === 'sign-in'" class="mt-6 space-y-4">
				<p class="text-p-base text-ink-gray-7">{{ signInMessage }}</p>
				<Button
					class="w-full"
					size="md"
					variant="solid"
					:route="signInPath"
					:label="registration.has_account ? __('Sign in') : __('Sign up')"
				/>
			</div>

			<div v-else-if="step === 'wrong-account'" class="mt-6 space-y-4">
				<p class="text-p-base text-ink-gray-7">
					{{ __('You are signed in as {0}. This link is for {1}.', [
						currentUser,
						registration.owner_email,
					]) }}
				</p>
				<ErrorMessage v-if="error" :message="error" />
				<Button
					class="w-full"
					size="md"
					variant="solid"
					:label="__('Switch account')"
					:loading="busy"
					@click="switchAccount"
				/>
			</div>

			<template v-else-if="step === 'choose-team'">
				<form
					v-if="teams.length"
					class="mt-6 space-y-4"
					@submit.prevent="complete(selectedTeam)"
				>
					<FormControl
						v-model="selectedTeam"
						type="select"
						size="md"
						:label="__('Team')"
						:options="teamOptions"
					/>
					<ErrorMessage v-if="error" :message="error" />
					<Button
						type="submit"
						class="w-full"
						size="md"
						variant="solid"
						:label="__('Use this team')"
						:disabled="!selectedTeam"
						:loading="busy"
					/>
				</form>
				<Button
					v-else
					class="mt-6 w-full"
					size="md"
					variant="solid"
					:label="__('Create team')"
					@click="creatingTeam = true"
				/>

				<p
					v-if="teams.length"
					class="mt-6 text-center text-p-sm text-ink-gray-5"
				>
					{{ __('Need a separate team?') }}
					<button
						type="button"
						class="text-p-sm-medium text-ink-gray-8 hover:underline"
						:disabled="busy"
						@click="creatingTeam = true"
					>
						{{ __('Create a new team') }}
					</button>
				</p>
			</template>

			<CreateTeamDialog
				v-model:open="creatingTeam"
				:default-name="registration.partner_name"
			/>
		</template>
	</AuthShell>
</template>
